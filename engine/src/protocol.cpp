#include "apex/protocol.hpp"
#include <chrono>
#include <sstream>

namespace apex {
namespace {
std::vector<std::string> split(const std::string& value, char delimiter) {
  std::vector<std::string> out;
  std::stringstream stream(value);
  for (std::string part; std::getline(stream, part, delimiter);) out.push_back(part);
  if (!value.empty() && value.back() == delimiter) out.emplace_back();
  return out;
}

std::string escape(const std::string& value) {
  std::string out;
  for (char c : value) {
    if (c == '"' || c == '\\') out.push_back('\\');
    if (c != '\n' && c != '\r') out.push_back(c);
  }
  return out;
}

std::int64_t millis(Clock::time_point value) {
  return std::chrono::duration_cast<std::chrono::milliseconds>(value.time_since_epoch()).count();
}

std::string order_json(const Order& o) {
  std::ostringstream s;
  s << "{\"id\":" << o.id << ",\"client_order_id\":\"" << escape(o.client_order_id)
    << "\",\"account_id\":" << o.account_id << ",\"symbol\":\"" << escape(o.symbol)
    << "\",\"side\":\"" << to_string(o.side) << "\",\"type\":\"" << to_string(o.type)
    << "\",\"quantity\":" << o.quantity << ",\"remaining_quantity\":" << o.remaining
    << ",\"price_ticks\":";
  if (o.price) s << *o.price; else s << "null";
  s << ",\"status\":\"" << to_string(o.status) << "\",\"created_at_ms\":" << millis(o.created_at) << "}";
  return s.str();
}

std::string trade_json(const Trade& t) {
  std::ostringstream s;
  s << "{\"id\":" << t.id << ",\"symbol\":\"" << escape(t.symbol)
    << "\",\"buy_order_id\":" << t.buy_order_id << ",\"sell_order_id\":" << t.sell_order_id
    << ",\"buyer_account_id\":" << t.buyer_account_id << ",\"seller_account_id\":" << t.seller_account_id
    << ",\"price_ticks\":" << t.price << ",\"quantity\":" << t.quantity
    << ",\"executed_at_ms\":" << millis(t.executed_at) << "}";
  return s.str();
}

std::string error(std::string message) { return "{\"ok\":false,\"error\":\"" + escape(message) + "\"}"; }
}

std::string handle_command(MatchingEngine& engine, const std::string& line) {
  try {
    const auto p = split(line, '|');
    if (p.empty()) return error("empty command");
    if (p[0] == "PING") return "{\"ok\":true,\"service\":\"matching-engine\"}";
    if (p[0] == "STATS") {
      return "{\"ok\":true,\"orders_received\":" + std::to_string(engine.orders_received()) +
        ",\"trades_executed\":" + std::to_string(engine.trades_executed()) +
        ",\"queue_depth\":" + std::to_string(engine.queue_depth()) +
        ",\"workers\":" + std::to_string(engine.worker_count()) + "}";
    }
    if (p[0] == "NEW") {
      if (p.size() != 9) return error("NEW expects 8 fields");
      Order order;
      order.id = std::stoull(p[1]);
      order.client_order_id = p[2];
      order.account_id = std::stoll(p[3]);
      order.symbol = p[4];
      order.side = p[5] == "BUY" ? Side::Buy : p[5] == "SELL" ? Side::Sell : throw std::invalid_argument("invalid side");
      order.type = p[6] == "LIMIT" ? OrderType::Limit : p[6] == "MARKET" ? OrderType::Market : throw std::invalid_argument("invalid type");
      order.quantity = std::stoll(p[7]);
      if (order.type == OrderType::Limit) order.price = std::stoll(p[8]);
      else if (!p[8].empty()) return error("market price must be empty");
      auto result = engine.submit(std::move(order)).get();
      std::string response = "{\"ok\":" + std::string(result.error.empty() ? "true" : "false") +
        ",\"order\":" + order_json(result.order) + ",\"trades\":[";
      for (std::size_t i = 0; i < result.trades.size(); ++i) {
        if (i) response += ',';
        response += trade_json(result.trades[i]);
      }
      response += "]";
      if (!result.error.empty()) response += ",\"error\":\"" + escape(result.error) + "\"";
      return response + "}";
    }
    if (p[0] == "CANCEL") {
      if (p.size() != 3) return error("CANCEL expects symbol and id");
      auto order = engine.cancel(p[1], std::stoull(p[2])).get();
      return order ? "{\"ok\":true,\"order\":" + order_json(*order) + "}" : error("active order not found");
    }
    if (p[0] == "GET") {
      if (p.size() != 3) return error("GET expects symbol and id");
      auto order = engine.find(p[1], std::stoull(p[2])).get();
      return order ? "{\"ok\":true,\"order\":" + order_json(*order) + "}" : error("order not found");
    }
    if (p[0] == "BOOK") {
      if (p.size() < 2 || p.size() > 3) return error("BOOK expects symbol and optional depth");
      auto book = engine.snapshot(p[1], p.size() == 3 ? std::stoull(p[2]) : 20).get();
      std::ostringstream s;
      s << "{\"ok\":true,\"symbol\":\"" << escape(book.symbol) << "\",\"bids\":[";
      auto levels = [&s](const auto& values) {
        for (std::size_t i = 0; i < values.size(); ++i) {
          if (i) s << ',';
          s << "{\"price_ticks\":" << values[i].price << ",\"quantity\":" << values[i].quantity
            << ",\"order_count\":" << values[i].order_count << "}";
        }
      };
      levels(book.bids); s << "],\"asks\":["; levels(book.asks); s << "]}";
      return s.str();
    }
    return error("unknown command");
  } catch (const std::exception& e) { return error(e.what()); }
}
}  // namespace apex
