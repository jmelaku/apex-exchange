#include "apex/matching_engine.hpp"
#include "apex/protocol.hpp"
#include <atomic>
#include <cstdlib>
#include <iostream>
#include <thread>

namespace {
int failures = 0;
#define CHECK(condition) do { if (!(condition)) { std::cerr << __FILE__ << ':' << __LINE__ << " CHECK failed: " #condition "\n"; ++failures; } } while (0)

apex::Order order(apex::Id id, std::int64_t account, std::string symbol, apex::Side side,
                  apex::OrderType type, std::int64_t quantity, std::optional<std::int64_t> price = {}) {
  return {id, "test-" + std::to_string(id), account, std::move(symbol), side, type,
          quantity, quantity, price, apex::OrderStatus::New, apex::Clock::now()};
}

void book_correctness() {
  apex::Id trade_id = 1;
  apex::OrderBook book("AAPL", [&] { return trade_id++; });
  CHECK(book.submit(order(1, 1, "AAPL", apex::Side::Sell, apex::OrderType::Limit, 10, 10100)).trades.empty());
  CHECK(book.submit(order(2, 2, "AAPL", apex::Side::Sell, apex::OrderType::Limit, 10, 10000)).trades.empty());
  auto result = book.submit(order(3, 3, "AAPL", apex::Side::Buy, apex::OrderType::Limit, 15, 10200));
  CHECK(result.trades.size() == 2);
  CHECK(result.trades[0].price == 10000 && result.trades[0].quantity == 10);
  CHECK(result.trades[1].price == 10100 && result.trades[1].quantity == 5);
  CHECK(result.order.status == apex::OrderStatus::Filled && result.order.remaining == 0);
  auto snapshot = book.snapshot();
  CHECK(snapshot.asks.size() == 1 && snapshot.asks[0].quantity == 5);
  std::string reason;
  CHECK(book.check_invariants(&reason));
}

void fifo_and_cancel() {
  apex::Id trade_id = 100;
  apex::OrderBook book("MSFT", [&] { return trade_id++; });
  book.submit(order(10, 1, "MSFT", apex::Side::Sell, apex::OrderType::Limit, 5, 20000));
  book.submit(order(11, 2, "MSFT", apex::Side::Sell, apex::OrderType::Limit, 5, 20000));
  auto result = book.submit(order(12, 3, "MSFT", apex::Side::Buy, apex::OrderType::Market, 6));
  CHECK(result.trades.size() == 2);
  CHECK(result.trades[0].sell_order_id == 10 && result.trades[1].sell_order_id == 11);
  CHECK(book.cancel(11).has_value());
  CHECK(!book.cancel(11).has_value());
  CHECK(book.find(11)->status == apex::OrderStatus::Cancelled);
  auto unfilled = book.submit(order(13, 4, "MSFT", apex::Side::Buy, apex::OrderType::Market, 10));
  CHECK(unfilled.order.status == apex::OrderStatus::Cancelled && unfilled.order.remaining == 10);
  CHECK(book.snapshot().bids.empty());
  CHECK(book.check_invariants());
}

void invalid_orders() {
  apex::Id trade_id = 1;
  apex::OrderBook book("AAPL", [&] { return trade_id++; });
  CHECK(!book.submit(order(1, 1, "WRONG", apex::Side::Buy, apex::OrderType::Limit, 1, 2)).error.empty());
  CHECK(!book.submit(order(2, 1, "AAPL", apex::Side::Buy, apex::OrderType::Limit, -1, 2)).error.empty());
  CHECK(!book.submit(order(3, 1, "AAPL", apex::Side::Buy, apex::OrderType::Limit, 1)).error.empty());
  CHECK(!book.submit(order(4, 0, "AAPL", apex::Side::Buy, apex::OrderType::Limit, 1, 2)).error.empty());
}

void concurrent_symbols() {
  apex::MatchingEngine engine(4);
  constexpr int threads = 8;
  constexpr int each = 1000;
  std::vector<std::thread> clients;
  std::atomic<int> trades{0};
  for (int t = 0; t < threads; ++t) {
    clients.emplace_back([&, t] {
      const std::string symbol = t % 2 ? "AAPL" : "MSFT";
      for (int i = 0; i < each; ++i) {
        apex::Order candidate{};
        candidate.client_order_id = std::to_string(t) + "-" + std::to_string(i);
        candidate.account_id = t + 1;
        candidate.symbol = symbol;
        candidate.side = (t + i) % 2 ? apex::Side::Buy : apex::Side::Sell;
        candidate.type = apex::OrderType::Limit;
        candidate.quantity = 1;
        candidate.price = 10000;
        trades.fetch_add(static_cast<int>(engine.submit(std::move(candidate)).get().trades.size()));
      }
    });
  }
  for (auto& client : clients) client.join();
  CHECK(engine.orders_received() == threads * each);
  CHECK(engine.trades_executed() == static_cast<std::uint64_t>(trades.load()));
  for (const auto* symbol : {"AAPL", "MSFT"}) {
    auto snapshot = engine.snapshot(symbol).get();
    CHECK(snapshot.bids.empty() || snapshot.asks.empty() || snapshot.bids[0].price < snapshot.asks[0].price);
  }
  auto stats = apex::handle_command(engine, "STATS");
  CHECK(stats.find("\"ok\":true") != std::string::npos);
  auto response = apex::handle_command(engine, "NEW|9001|protocol-id|99|GOOG|BUY|LIMIT|2|12345");
  CHECK(response.find("\"id\":9001") != std::string::npos);
  auto market = apex::handle_command(engine, "NEW|9002|market-id|98|GOOG|SELL|MARKET|2|");
  CHECK(market.find("\"id\":9002") != std::string::npos && market.find("\"trades\":[{") != std::string::npos);
}
}

int main() {
  book_correctness();
  fifo_and_cancel();
  invalid_orders();
  concurrent_symbols();
  if (failures) { std::cerr << failures << " test(s) failed\n"; return EXIT_FAILURE; }
  std::cout << "all engine tests passed\n";
}
