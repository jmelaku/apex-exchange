#include <algorithm>
#include <arpa/inet.h>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <iostream>
#include <netdb.h>
#include <optional>
#include <poll.h>
#include <random>
#include <sstream>
#include <string>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace {

std::atomic<bool> running{true};

void stop(int) { running.store(false); }

int env_int(const char* name, int fallback) {
  const char* value = std::getenv(name);
  return value ? std::atoi(value) : fallback;
}

double env_double(const char* name, double fallback) {
  const char* value = std::getenv(name);
  return value ? std::atof(value) : fallback;
}

std::string env_string(const char* name, const std::string& fallback) {
  const char* value = std::getenv(name);
  return value ? value : fallback;
}

std::string json_escape(const std::string& value) {
  std::string escaped;
  escaped.reserve(value.size());
  for (const char character : value) {
    if (character == '"' || character == '\\') escaped.push_back('\\');
    if (character == '\n' || character == '\r') escaped.push_back(' ');
    else escaped.push_back(character);
  }
  return escaped;
}

void log(const std::string& event, pid_t pid, const std::string& detail = {}) {
  std::cerr << "{\"service\":\"simulator\",\"event\":\"" << event << "\",\"pid\":" << pid
            << ",\"detail\":\"" << json_escape(detail) << "\"}\n";
}

std::vector<std::string> split(const std::string& value, char delimiter) {
  std::vector<std::string> parts;
  std::stringstream stream(value);
  std::string part;
  while (std::getline(stream, part, delimiter)) {
    if (!part.empty()) parts.push_back(part);
  }
  return parts;
}

struct Market {
  std::string symbol;
  std::int64_t anchor;
  std::int64_t mid;
  std::int64_t minimum;
  std::int64_t maximum;
  std::int64_t quote_step;
  std::int64_t walk_step;
};

std::optional<Market> market_for(const std::string& symbol) {
  if (symbol == "AAPL") return Market{symbol, 20000, 20000, 19600, 20400, 2, 2};
  if (symbol == "MSFT") return Market{symbol, 18500, 18500, 18130, 18870, 2, 2};
  if (symbol == "NVDA") return Market{symbol, 20000, 20000, 19600, 20400, 3, 3};
  if (symbol == "BTCUSD") return Market{symbol, 6000000, 6000000, 5880000, 6120000, 100, 200};
  return std::nullopt;
}

std::vector<Market> configured_markets() {
  std::vector<Market> markets;
  for (const auto& symbol : split(env_string("SIM_SYMBOLS", "AAPL,MSFT,NVDA,BTCUSD"), ',')) {
    if (auto market = market_for(symbol)) markets.push_back(*market);
    else log("unknown_symbol_ignored", getpid(), symbol);
  }
  if (markets.empty()) throw std::runtime_error("SIM_SYMBOLS contains no supported instruments");
  return markets;
}

struct Child {
  pid_t pid{};
  int read_fd{-1};
  int index{};
  int restarts{};
  std::string pending;
};

std::string limit_order(int account, const Market& market, const std::string& side,
                        std::int64_t quantity, std::int64_t price) {
  return "ORDER|" + std::to_string(account) + "|" + market.symbol + "|" + side +
         "|LIMIT|" + std::to_string(quantity) + "|" + std::to_string(price);
}

std::string market_order(int account, const Market& market, const std::string& side,
                         std::int64_t quantity) {
  return "ORDER|" + std::to_string(account) + "|" + market.symbol + "|" + side +
         "|MARKET|" + std::to_string(quantity) + "|0";
}

std::int64_t quantity_for(const Market& market, std::mt19937_64& generator, bool aggressive) {
  if (market.symbol == "BTCUSD") return 1;
  const int maximum = aggressive ? 8 : 20;
  return std::uniform_int_distribution<int>(1, maximum)(generator);
}

std::string next_intent(std::vector<Market>& markets, std::mt19937_64& generator,
                        std::uint64_t sequence, double volatility, int maker_account,
                        int taker_account) {
  Market& market = markets[std::uniform_int_distribution<std::size_t>(0, markets.size() - 1)(generator)];
  const auto scaled_walk = std::max<std::int64_t>(0, std::llround(market.walk_step * volatility));
  market.mid = std::clamp(
      market.mid + std::uniform_int_distribution<std::int64_t>(-scaled_walk, scaled_walk)(generator),
      market.minimum, market.maximum);

  const int choice = std::uniform_int_distribution<int>(0, 99)(generator);
  const std::string side = (sequence % 2 == 0) ? "BUY" : "SELL";
  if (choice < 45) {
    const bool buy = std::uniform_int_distribution<int>(0, 1)(generator) == 0;
    const auto levels = std::uniform_int_distribution<int>(1, 6)(generator);
    const auto price = market.mid + (buy ? -1 : 1) * market.quote_step * levels;
    return limit_order(maker_account, market, buy ? "BUY" : "SELL", quantity_for(market, generator, false), price);
  }
  if (choice < 65) return "CANCEL|" + std::to_string(maker_account) + "|" + market.symbol;
  if (choice < 87) {
    const auto crossing_price = market.mid + (side == "BUY" ? 1 : -1) * market.quote_step * 20;
    return limit_order(taker_account, market, side, quantity_for(market, generator, true), crossing_price);
  }
  return market_order(taker_account, market, side, quantity_for(market, generator, true));
}

Child spawn(int index, int restart_count, int child_count) {
  int channel[2];
  if (::pipe(channel) != 0) throw std::runtime_error(std::strerror(errno));
  const pid_t pid = ::fork();
  if (pid < 0) throw std::runtime_error(std::strerror(errno));
  if (pid == 0) {
    ::close(channel[0]);
    const int event_limit = env_int("SIM_EVENTS_PER_CHILD", 0);
    const int maker_account = std::max(1, env_int("SIM_MAKER_ACCOUNT", 3));
    const int taker_account = std::max(1, env_int("SIM_TAKER_ACCOUNT", 4));
    const int depth_levels = std::max(1, env_int("SIM_DEPTH_LEVELS", 3));
    const double events_per_second = std::max(0.1, env_double("SIM_EVENTS_PER_SECOND", 4.0));
    const double volatility = std::max(0.0, env_double("SIM_VOLATILITY", 1.0));
    const int configured_interval = env_int("SIM_INTERVAL_MS", 0);
    const int interval_ms = configured_interval > 0
        ? configured_interval
        : std::max(10, static_cast<int>(std::llround(1000.0 * child_count / events_per_second)));
    const std::uint64_t seed = static_cast<std::uint64_t>(env_int("SIM_SEED", 424242));
    std::mt19937_64 generator(seed + static_cast<std::uint64_t>(index + 1) * 0x9e3779b97f4a7c15ULL +
                              static_cast<std::uint64_t>(restart_count));
    const bool fail_once = std::getenv("SIMULATE_CHILD_FAILURE") && restart_count == 0 && index == 0;

    const auto all_markets = configured_markets();
    std::vector<Market> owned;
    for (std::size_t position = 0; position < all_markets.size(); ++position) {
      if (static_cast<int>(position % static_cast<std::size_t>(child_count)) == index) owned.push_back(all_markets[position]);
    }
    if (owned.empty()) owned.push_back(all_markets[static_cast<std::size_t>(index) % all_markets.size()]);

    std::deque<std::string> startup;
    for (const auto& market : owned) {
      for (int level = 1; level <= depth_levels; ++level) {
        startup.push_back(limit_order(maker_account, market, "BUY", market.symbol == "BTCUSD" ? 1 : 5 + level * 2,
                                      market.mid - market.quote_step * level));
        startup.push_back(limit_order(maker_account, market, "SELL", market.symbol == "BTCUSD" ? 1 : 4 + level * 3,
                                      market.mid + market.quote_step * level));
      }
    }

    std::uint64_t sequence = 0;
    while (running.load() && (event_limit <= 0 || static_cast<int>(sequence) < event_limit)) {
      const std::string intent = startup.empty()
          ? next_intent(owned, generator, sequence, volatility, maker_account, taker_account)
          : std::move(startup.front());
      if (!startup.empty()) startup.pop_front();
      const std::string framed = intent + "\n";
      if (::write(channel[1], framed.data(), framed.size()) < 0) _exit(2);
      if (fail_once && sequence == 0) _exit(42);
      ++sequence;
      std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
    }
    ::close(channel[1]);
    _exit(0);
  }
  ::close(channel[1]);
  log("child_started", pid, "feed=" + std::to_string(index));
  return Child{pid, channel[0], index, restart_count, {}};
}

struct HttpResponse {
  int status{};
  std::string body;
};

std::optional<HttpResponse> http_request(const std::string& method, const std::string& path,
                                         const std::string& body = {}) {
  const std::string host = env_string("API_HOST", "api");
  const std::string port = env_string("API_PORT", "8000");
  addrinfo hints{};
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;
  addrinfo* addresses = nullptr;
  if (::getaddrinfo(host.c_str(), port.c_str(), &hints, &addresses) != 0) return std::nullopt;
  int descriptor = -1;
  for (auto* address = addresses; address; address = address->ai_next) {
    descriptor = ::socket(address->ai_family, address->ai_socktype, address->ai_protocol);
    if (descriptor >= 0 && ::connect(descriptor, address->ai_addr, address->ai_addrlen) == 0) break;
    if (descriptor >= 0) ::close(descriptor);
    descriptor = -1;
  }
  ::freeaddrinfo(addresses);
  if (descriptor < 0) return std::nullopt;

  std::string request = method + " " + path + " HTTP/1.1\r\nHost: " + host +
      "\r\nAccept: application/json\r\nConnection: close\r\n";
  if (!body.empty()) {
    request += "Content-Type: application/json\r\nContent-Length: " + std::to_string(body.size()) + "\r\n";
  }
  request += "\r\n" + body;
  std::size_t sent = 0;
  while (sent < request.size()) {
    const auto bytes = ::send(descriptor, request.data() + sent, request.size() - sent, MSG_NOSIGNAL);
    if (bytes <= 0) { ::close(descriptor); return std::nullopt; }
    sent += static_cast<std::size_t>(bytes);
  }
  std::string response;
  char buffer[2048];
  for (ssize_t bytes; (bytes = ::recv(descriptor, buffer, sizeof(buffer), 0)) > 0;) {
    response.append(buffer, static_cast<std::size_t>(bytes));
  }
  ::close(descriptor);
  const auto first_space = response.find(' ');
  if (first_space == std::string::npos) return std::nullopt;
  const int status = std::atoi(response.c_str() + static_cast<long>(first_space + 1));
  const auto separator = response.find("\r\n\r\n");
  return HttpResponse{status, separator == std::string::npos ? std::string{} : response.substr(separator + 4)};
}

std::optional<std::int64_t> json_integer(const std::string& body, const std::string& key) {
  const std::string token = "\"" + key + "\":";
  auto position = body.find(token);
  if (position == std::string::npos) return std::nullopt;
  position += token.size();
  while (position < body.size() && body[position] == ' ') ++position;
  char* end = nullptr;
  const auto value = std::strtoll(body.c_str() + static_cast<long>(position), &end, 10);
  return end == body.c_str() + static_cast<long>(position) ? std::nullopt : std::optional<std::int64_t>(value);
}

std::optional<std::string> json_string(const std::string& body, const std::string& key) {
  const std::string token = "\"" + key + "\":\"";
  const auto position = body.find(token);
  if (position == std::string::npos) return std::nullopt;
  const auto begin = position + token.size();
  const auto end = body.find('"', begin);
  return end == std::string::npos ? std::nullopt : std::optional<std::string>(body.substr(begin, end - begin));
}

struct ActiveOrder {
  std::int64_t id;
  int account;
  std::string symbol;
};

bool cancel_one(std::vector<ActiveOrder>& active, int account, const std::string& symbol) {
  const auto candidate = std::find_if(active.begin(), active.end(), [&](const ActiveOrder& order) {
    return order.account == account && order.symbol == symbol;
  });
  if (candidate == active.end()) {
    log("cancel_skipped", getpid(), "no active order account=" + std::to_string(account) + " symbol=" + symbol);
    return true;
  }
  const auto id = candidate->id;
  const auto response = http_request("DELETE", "/orders/" + std::to_string(id));
  active.erase(candidate);
  if (!response) return false;
  if (response->status == 200) {
    log("order_cancelled", getpid(), "order_id=" + std::to_string(id) + " symbol=" + symbol);
    return true;
  }
  // A matched order may remain in this local registry until selected. A 409 simply
  // proves it is no longer cancellable, so dropping the stale entry is correct.
  if (response->status == 409 || response->status == 404) return true;
  log("cancel_failed", getpid(), "order_id=" + std::to_string(id) + " status=" + std::to_string(response->status));
  return false;
}

bool dispatch_intent(const std::string& line, std::vector<ActiveOrder>& active) {
  const bool dry_run = env_string("SIM_DRY_RUN", "0") == "1";
  if (dry_run) { std::cout << line << '\n'; return true; }
  const auto parts = split(line, '|');
  if (parts.empty()) return false;
  if (parts[0] == "CANCEL" && parts.size() == 3) {
    return cancel_one(active, std::stoi(parts[1]), parts[2]);
  }
  if (parts[0] != "ORDER" || parts.size() != 7) return false;

  const int account = std::stoi(parts[1]);
  const std::string& symbol = parts[2];
  const std::string& type = parts[4];
  const int maker_account = std::max(1, env_int("SIM_MAKER_ACCOUNT", 3));
  const int max_open = std::max(2, env_int("SIM_MAX_OPEN_PER_SYMBOL", 12));
  const auto open_for_symbol = std::count_if(active.begin(), active.end(), [&](const ActiveOrder& order) {
    return order.account == maker_account && order.symbol == symbol;
  });
  if (account == maker_account && open_for_symbol >= max_open && !cancel_one(active, maker_account, symbol)) return false;

  std::string body = "{\"account_id\":" + parts[1] + ",\"symbol\":\"" + symbol +
      "\",\"side\":\"" + parts[3] + "\",\"order_type\":\"" + type +
      "\",\"quantity\":" + parts[5];
  if (type == "LIMIT") body += ",\"price_ticks\":" + parts[6];
  body += "}";
  const auto response = http_request("POST", "/orders", body);
  if (!response) return false;
  if (response->status != 200 && response->status != 201) {
    log("order_rejected", getpid(), "status=" + std::to_string(response->status) + " intent=" + line);
    return false;
  }
  const auto id = json_integer(response->body, "id");
  const auto status = json_string(response->body, "status");
  if (id && status && (*status == "NEW" || *status == "PARTIALLY_FILLED")) {
    active.push_back(ActiveOrder{*id, account, symbol});
  }
  log("order_submitted", getpid(), "order_id=" + std::to_string(id.value_or(0)) + " symbol=" + symbol +
      " status=" + status.value_or("UNKNOWN"));
  return true;
}

}  // namespace

int main() {
  std::signal(SIGINT, stop);
  std::signal(SIGTERM, stop);
  const int child_count = std::max(1, env_int("SIM_CHILDREN", 2));
  std::vector<Child> children;
  for (int index = 0; index < child_count; ++index) children.push_back(spawn(index, 0, child_count));
  std::vector<ActiveOrder> active_orders;
  int forwarded = 0;
  int failed = 0;
  while (running.load() && !children.empty()) {
    std::vector<pollfd> descriptors;
    for (const auto& child : children) descriptors.push_back({child.read_fd, POLLIN | POLLHUP, 0});
    const int ready = ::poll(descriptors.data(), descriptors.size(), 500);
    if (ready < 0 && errno != EINTR) break;
    for (std::size_t index = children.size(); index-- > 0;) {
      if (!(descriptors[index].revents & (POLLIN | POLLHUP))) continue;
      char buffer[1024];
      const auto bytes = ::read(children[index].read_fd, buffer, sizeof(buffer));
      if (bytes > 0) {
        children[index].pending.append(buffer, static_cast<std::size_t>(bytes));
        for (std::size_t end; (end = children[index].pending.find('\n')) != std::string::npos;) {
          const auto intent = children[index].pending.substr(0, end);
          children[index].pending.erase(0, end + 1);
          if (dispatch_intent(intent, active_orders)) ++forwarded;
          else { ++failed; log("forward_failed", getpid(), intent); }
        }
      } else {
        ::close(children[index].read_fd);
        int status = 0;
        ::waitpid(children[index].pid, &status, 0);
        log("child_reaped", children[index].pid,
            "status=" + std::to_string(WIFEXITED(status) ? WEXITSTATUS(status) : -1));
        const int feed = children[index].index;
        const int restarts = children[index].restarts;
        children.erase(children.begin() + static_cast<long>(index));
        if (running.load() && (!WIFEXITED(status) || WEXITSTATUS(status) != 0) && restarts < 2) {
          children.push_back(spawn(feed, restarts + 1, child_count));
        }
      }
    }
  }
  for (auto& child : children) {
    ::kill(child.pid, SIGTERM);
    ::close(child.read_fd);
    ::waitpid(child.pid, nullptr, 0);
  }
  log("supervisor_stopped", getpid(), "forwarded=" + std::to_string(forwarded) + " failed=" + std::to_string(failed));
  return running.load() && failed ? 1 : 0;
}
