#pragma once

#include "apex/types.hpp"
#include <atomic>
#include <functional>
#include <list>
#include <map>
#include <memory>
#include <unordered_map>

namespace apex {

class OrderBook {
 public:
  using TradeIdGenerator = std::function<Id()>;
  explicit OrderBook(std::string symbol, TradeIdGenerator next_trade_id);

  SubmissionResult submit(Order order);
  std::optional<Order> cancel(Id order_id);
  std::optional<Order> find(Id order_id) const;
  BookSnapshot snapshot(std::size_t depth = 20) const;
  bool check_invariants(std::string* reason = nullptr) const;

 private:
  using Queue = std::list<std::shared_ptr<Order>>;
  using Bids = std::map<std::int64_t, Queue, std::greater<std::int64_t>>;
  using Asks = std::map<std::int64_t, Queue>;
  struct Locator { Side side; std::int64_t price; Queue::iterator iterator; };

  template <typename OppositeLevels>
  void match(Order& incoming, OppositeLevels& opposite, std::vector<Trade>& trades);
  void rest(std::shared_ptr<Order> order);

  std::string symbol_;
  TradeIdGenerator next_trade_id_;
  Bids bids_;
  Asks asks_;
  std::unordered_map<Id, Locator> active_;
  std::unordered_map<Id, std::shared_ptr<Order>> orders_;
};

}  // namespace apex
