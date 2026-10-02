#include "apex/order_book.hpp"
#include <algorithm>
#include <stdexcept>

namespace apex {

OrderBook::OrderBook(std::string symbol, TradeIdGenerator next_trade_id)
    : symbol_(std::move(symbol)), next_trade_id_(std::move(next_trade_id)) {}

template <typename OppositeLevels>
void OrderBook::match(Order& incoming, OppositeLevels& opposite, std::vector<Trade>& trades) {
  while (incoming.remaining > 0 && !opposite.empty()) {
    auto level = opposite.begin();
    const auto best_price = level->first;
    const bool crosses = incoming.type == OrderType::Market ||
      (incoming.side == Side::Buy ? *incoming.price >= best_price : *incoming.price <= best_price);
    if (!crosses) break;

    auto& fifo = level->second;
    while (incoming.remaining > 0 && !fifo.empty()) {
      auto resting = fifo.front();
      if (resting->status == OrderStatus::Cancelled || resting->remaining <= 0)
        throw std::logic_error("inactive order present in book");
      // Self-trade prevention: cancel the older resting order instead of manufacturing
      // volume with identical beneficial ownership. The incoming order is cancelled so
      // the durable resting order and its reservation remain consistent.
      if (resting->account_id == incoming.account_id) {
        incoming.status = OrderStatus::Cancelled;
        return;
      }
      const auto executed = std::min(incoming.remaining, resting->remaining);
      incoming.remaining -= executed;
      resting->remaining -= executed;
      incoming.status = incoming.remaining == 0 ? OrderStatus::Filled : OrderStatus::PartiallyFilled;
      resting->status = resting->remaining == 0 ? OrderStatus::Filled : OrderStatus::PartiallyFilled;

      const bool incoming_buy = incoming.side == Side::Buy;
      trades.push_back(Trade{
          next_trade_id_(), symbol_,
          incoming_buy ? incoming.id : resting->id,
          incoming_buy ? resting->id : incoming.id,
          incoming_buy ? incoming.account_id : resting->account_id,
          incoming_buy ? resting->account_id : incoming.account_id,
          best_price, executed, Clock::now()});

      if (resting->remaining == 0) {
        active_.erase(resting->id);
        fifo.pop_front();
      }
    }
    if (fifo.empty()) opposite.erase(level);
  }
}

void OrderBook::rest(std::shared_ptr<Order> order) {
  if (order->side == Side::Buy) {
    auto& queue = bids_[*order->price];
    queue.push_back(order);
    active_.emplace(order->id, Locator{order->side, *order->price, std::prev(queue.end())});
  } else {
    auto& queue = asks_[*order->price];
    queue.push_back(order);
    active_.emplace(order->id, Locator{order->side, *order->price, std::prev(queue.end())});
  }
}

SubmissionResult OrderBook::submit(Order order) {
  SubmissionResult result;
  if (order.id == 0 || order.account_id <= 0 || order.symbol != symbol_ || order.quantity <= 0 ||
      (order.type == OrderType::Limit && (!order.price || *order.price <= 0)) ||
      (order.type == OrderType::Market && order.price)) {
    order.status = OrderStatus::Rejected;
    result.order = std::move(order);
    result.error = "invalid order";
    return result;
  }
  if (orders_.contains(order.id)) {
    order.status = OrderStatus::Rejected;
    result.order = std::move(order);
    result.error = "duplicate order id";
    return result;
  }
  order.remaining = order.quantity;
  order.status = OrderStatus::New;
  auto stored = std::make_shared<Order>(order);
  orders_[order.id] = stored;

  if (order.side == Side::Buy) match(*stored, asks_, result.trades);
  else match(*stored, bids_, result.trades);

  if (stored->remaining > 0 && stored->status != OrderStatus::Cancelled) {
    if (stored->type == OrderType::Limit) {
      rest(stored);
      if (!result.trades.empty()) stored->status = OrderStatus::PartiallyFilled;
    } else {
      // The unfilled part of a market order expires immediately; it never rests.
      stored->status = OrderStatus::Cancelled;
    }
  }
  result.order = *stored;
  return result;
}

std::optional<Order> OrderBook::cancel(Id order_id) {
  auto found = active_.find(order_id);
  if (found == active_.end()) return std::nullopt;
  const auto locator = found->second;
  auto order = *locator.iterator;
  if (locator.side == Side::Buy) {
    auto level = bids_.find(locator.price);
    level->second.erase(locator.iterator);
    if (level->second.empty()) bids_.erase(level);
  } else {
    auto level = asks_.find(locator.price);
    level->second.erase(locator.iterator);
    if (level->second.empty()) asks_.erase(level);
  }
  active_.erase(found);
  order->status = OrderStatus::Cancelled;
  return *order;
}

std::optional<Order> OrderBook::find(Id id) const {
  auto it = orders_.find(id);
  return it == orders_.end() ? std::nullopt : std::optional<Order>(*it->second);
}

BookSnapshot OrderBook::snapshot(std::size_t depth) const {
  BookSnapshot out{symbol_, {}, {}};
  auto aggregate = [depth](const auto& levels, auto& target) {
    for (const auto& [price, queue] : levels) {
      if (target.size() >= depth) break;
      std::int64_t quantity = 0;
      for (const auto& order : queue) quantity += order->remaining;
      target.push_back(PriceLevel{price, quantity, queue.size()});
    }
  };
  aggregate(bids_, out.bids);
  aggregate(asks_, out.asks);
  return out;
}

bool OrderBook::check_invariants(std::string* reason) const {
  std::size_t count = 0;
  auto check = [&](const auto& levels, Side expected) {
    for (const auto& [price, queue] : levels) {
      if (price <= 0 || queue.empty()) return false;
      for (const auto& order : queue) {
        ++count;
        if (order->side != expected || order->remaining <= 0 || order->remaining > order->quantity ||
            order->status == OrderStatus::Filled || order->status == OrderStatus::Cancelled ||
            !order->price || *order->price != price) return false;
        auto loc = active_.find(order->id);
        if (loc == active_.end()) return false;
      }
    }
    return true;
  };
  const bool ok = check(bids_, Side::Buy) && check(asks_, Side::Sell) && count == active_.size() &&
                  (bids_.empty() || asks_.empty() || bids_.begin()->first < asks_.begin()->first);
  if (!ok && reason) *reason = "book contains invalid/crossed/uncatalogued orders";
  return ok;
}

}  // namespace apex
