#include "apex/matching_engine.hpp"
#include <stdexcept>

namespace apex {

MatchingEngine::MatchingEngine(std::size_t count) {
  if (count == 0) throw std::invalid_argument("worker count must be positive");
  // Reserve one million IDs per wall-clock millisecond. This keeps trade identifiers
  // unique across ordinary process restarts while the database remains persistent.
  const auto epoch_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
    Clock::now().time_since_epoch()).count();
  next_trade_id_.store(static_cast<Id>(epoch_ms) * 1'000'000, std::memory_order_relaxed);
  workers_.reserve(count);
  for (std::size_t i = 0; i < count; ++i) workers_.push_back(std::make_unique<Worker>());
  for (auto& worker : workers_) worker->thread = std::thread([this, ptr = worker.get()] { run(*ptr); });
}

MatchingEngine::~MatchingEngine() {
  for (auto& worker : workers_) {
    { std::lock_guard lock(worker->mutex); worker->stopping = true; }
    worker->ready.notify_all();
  }
  for (auto& worker : workers_) if (worker->thread.joinable()) worker->thread.join();
}

MatchingEngine::Worker& MatchingEngine::worker_for(const std::string& symbol) {
  return *workers_[std::hash<std::string>{}(symbol) % workers_.size()];
}

OrderBook& MatchingEngine::book(Worker& worker, const std::string& symbol) {
  auto [it, inserted] = worker.books.try_emplace(symbol);
  if (inserted) {
    it->second = std::make_unique<OrderBook>(symbol, [this] {
      return next_trade_id_.fetch_add(1, std::memory_order_relaxed);
    });
  }
  return *it->second;
}

void MatchingEngine::run(Worker& worker) {
  for (;;) {
    std::function<void()> job;
    {
      std::unique_lock lock(worker.mutex);
      worker.ready.wait(lock, [&] { return worker.stopping || !worker.jobs.empty(); });
      if (worker.stopping && worker.jobs.empty()) return;
      job = std::move(worker.jobs.front());
      worker.jobs.pop();
    }
    job();
  }
}

std::future<SubmissionResult> MatchingEngine::submit(Order order) {
  if (order.id == 0) {
    order.id = next_order_id();
  } else {
    auto expected = next_order_id_.load(std::memory_order_relaxed);
    while (expected <= order.id && !next_order_id_.compare_exchange_weak(
      expected, order.id + 1, std::memory_order_relaxed)) {}
  }
  if (order.created_at.time_since_epoch().count() == 0) order.created_at = Clock::now();
  auto& worker = worker_for(order.symbol);
  auto task = std::make_shared<std::packaged_task<SubmissionResult()>>(
    [this, &worker, order = std::move(order)]() mutable {
      orders_received_.fetch_add(1, std::memory_order_relaxed);
      auto result = book(worker, order.symbol).submit(std::move(order));
      trades_executed_.fetch_add(result.trades.size(), std::memory_order_relaxed);
      return result;
    });
  auto future = task->get_future();
  { std::lock_guard lock(worker.mutex); worker.jobs.emplace([task] { (*task)(); }); }
  worker.ready.notify_one();
  return future;
}

std::future<std::optional<Order>> MatchingEngine::cancel(std::string symbol, Id id) {
  auto& worker = worker_for(symbol);
  auto task = std::make_shared<std::packaged_task<std::optional<Order>()>>(
    [this, &worker, symbol = std::move(symbol), id] { return book(worker, symbol).cancel(id); });
  auto future = task->get_future();
  { std::lock_guard lock(worker.mutex); worker.jobs.emplace([task] { (*task)(); }); }
  worker.ready.notify_one();
  return future;
}

std::future<std::optional<Order>> MatchingEngine::find(std::string symbol, Id id) {
  auto& worker = worker_for(symbol);
  auto task = std::make_shared<std::packaged_task<std::optional<Order>()>>(
    [this, &worker, symbol = std::move(symbol), id] { return book(worker, symbol).find(id); });
  auto future = task->get_future();
  { std::lock_guard lock(worker.mutex); worker.jobs.emplace([task] { (*task)(); }); }
  worker.ready.notify_one();
  return future;
}

std::future<BookSnapshot> MatchingEngine::snapshot(std::string symbol, std::size_t depth) {
  auto& worker = worker_for(symbol);
  auto task = std::make_shared<std::packaged_task<BookSnapshot()>>(
    [this, &worker, symbol = std::move(symbol), depth] { return book(worker, symbol).snapshot(depth); });
  auto future = task->get_future();
  { std::lock_guard lock(worker.mutex); worker.jobs.emplace([task] { (*task)(); }); }
  worker.ready.notify_one();
  return future;
}

std::size_t MatchingEngine::queue_depth() const {
  std::size_t total = 0;
  for (const auto& worker : workers_) {
    std::lock_guard lock(worker->mutex);
    total += worker->jobs.size();
  }
  return total;
}

}  // namespace apex
