#pragma once

#include "apex/order_book.hpp"
#include <atomic>
#include <condition_variable>
#include <future>
#include <memory>
#include <mutex>
#include <queue>
#include <thread>

namespace apex {

class MatchingEngine {
 public:
  explicit MatchingEngine(std::size_t workers);
  ~MatchingEngine();
  MatchingEngine(const MatchingEngine&) = delete;
  MatchingEngine& operator=(const MatchingEngine&) = delete;

  std::future<SubmissionResult> submit(Order order);
  std::future<std::optional<Order>> cancel(std::string symbol, Id id);
  std::future<std::optional<Order>> find(std::string symbol, Id id);
  std::future<BookSnapshot> snapshot(std::string symbol, std::size_t depth = 20);
  Id next_order_id() { return next_order_id_.fetch_add(1, std::memory_order_relaxed); }
  std::uint64_t orders_received() const { return orders_received_.load(); }
  std::uint64_t trades_executed() const { return trades_executed_.load(); }
  std::size_t worker_count() const { return workers_.size(); }
  std::size_t queue_depth() const;

 private:
  struct Worker {
    std::mutex mutex;
    std::condition_variable ready;
    std::queue<std::function<void()>> jobs;
    std::unordered_map<std::string, std::unique_ptr<OrderBook>> books;
    bool stopping{false};
    std::thread thread;
  };

  Worker& worker_for(const std::string& symbol);
  OrderBook& book(Worker& worker, const std::string& symbol);
  void run(Worker& worker);

  std::vector<std::unique_ptr<Worker>> workers_;
  std::atomic<Id> next_order_id_{1};
  std::atomic<Id> next_trade_id_{1};
  std::atomic<std::uint64_t> orders_received_{0};
  std::atomic<std::uint64_t> trades_executed_{0};
};

}  // namespace apex
