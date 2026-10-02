#pragma once

#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace apex {

using Id = std::uint64_t;
using Clock = std::chrono::system_clock;

enum class Side { Buy, Sell };
enum class OrderType { Limit, Market };
enum class OrderStatus { New, PartiallyFilled, Filled, Cancelled, Rejected };

struct Instrument {
  std::string symbol;
  std::string name;
  std::int64_t tick_size{1};
};

// Prices are integer ticks and quantities are integer units. Avoiding floating point in
// the engine is an important financial invariant.
struct Order {
  Id id{};
  std::string client_order_id;
  std::int64_t account_id{};
  std::string symbol;
  Side side{};
  OrderType type{};
  std::int64_t quantity{};
  std::int64_t remaining{};
  std::optional<std::int64_t> price;
  OrderStatus status{OrderStatus::New};
  Clock::time_point created_at{Clock::now()};
};

struct Trade {
  Id id{};
  std::string symbol;
  Id buy_order_id{};
  Id sell_order_id{};
  std::int64_t buyer_account_id{};
  std::int64_t seller_account_id{};
  std::int64_t price{};
  std::int64_t quantity{};
  Clock::time_point executed_at{Clock::now()};
};

struct SubmissionResult {
  Order order;
  std::vector<Trade> trades;
  std::string error;
};

struct PriceLevel {
  std::int64_t price{};
  std::int64_t quantity{};
  std::size_t order_count{};
};

struct BookSnapshot {
  std::string symbol;
  std::vector<PriceLevel> bids;
  std::vector<PriceLevel> asks;
};

inline const char* to_string(Side v) { return v == Side::Buy ? "BUY" : "SELL"; }
inline const char* to_string(OrderType v) { return v == OrderType::Limit ? "LIMIT" : "MARKET"; }
inline const char* to_string(OrderStatus v) {
  switch (v) {
    case OrderStatus::New: return "NEW";
    case OrderStatus::PartiallyFilled: return "PARTIALLY_FILLED";
    case OrderStatus::Filled: return "FILLED";
    case OrderStatus::Cancelled: return "CANCELLED";
    case OrderStatus::Rejected: return "REJECTED";
  }
  return "REJECTED";
}

}  // namespace apex
