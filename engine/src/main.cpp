#include "apex/protocol.hpp"
#include <arpa/inet.h>
#include <atomic>
#include <csignal>
#include <cstring>
#include <iostream>
#include <netinet/in.h>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>

namespace {
std::atomic<bool> running{true};
int server_fd = -1;
void stop(int) {
  running.store(false);
  if (server_fd >= 0) ::shutdown(server_fd, SHUT_RDWR);
}
void log(const char* level, const std::string& event, const std::string& detail = {}) {
  std::cerr << "{\"level\":\"" << level << "\",\"service\":\"matching-engine\",\"event\":\""
            << event << "\",\"detail\":\"" << detail << "\"}\n";
}
void serve_client(int fd, apex::MatchingEngine& engine) {
  std::string pending;
  char buffer[4096];
  while (running.load()) {
    const auto count = ::recv(fd, buffer, sizeof(buffer), 0);
    if (count <= 0) break;
    pending.append(buffer, static_cast<std::size_t>(count));
    for (std::size_t newline; (newline = pending.find('\n')) != std::string::npos;) {
      auto command = pending.substr(0, newline);
      pending.erase(0, newline + 1);
      auto response = apex::handle_command(engine, command) + "\n";
      std::size_t sent = 0;
      while (sent < response.size()) {
        const auto n = ::send(fd, response.data() + sent, response.size() - sent, MSG_NOSIGNAL);
        if (n <= 0) { ::close(fd); return; }
        sent += static_cast<std::size_t>(n);
      }
    }
  }
  ::close(fd);
}
}

int main() {
  std::signal(SIGINT, stop);
  std::signal(SIGTERM, stop);
  const auto worker_count = static_cast<std::size_t>(std::max(1, std::atoi(std::getenv("ENGINE_WORKERS") ? std::getenv("ENGINE_WORKERS") : "4")));
  const int port = std::atoi(std::getenv("ENGINE_PORT") ? std::getenv("ENGINE_PORT") : "9001");
  apex::MatchingEngine engine(worker_count);
  server_fd = ::socket(AF_INET, SOCK_STREAM, 0);
  if (server_fd < 0) { log("error", "socket_failed", std::strerror(errno)); return 1; }
  int reuse = 1;
  ::setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
  sockaddr_in address{};
  address.sin_family = AF_INET;
  address.sin_addr.s_addr = htonl(INADDR_ANY);
  address.sin_port = htons(static_cast<std::uint16_t>(port));
  if (::bind(server_fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) < 0 || ::listen(server_fd, 128) < 0) {
    log("error", "listen_failed", std::strerror(errno)); return 1;
  }
  log("info", "started", "port=" + std::to_string(port) + " workers=" + std::to_string(worker_count));
  std::vector<std::thread> clients;
  while (running.load()) {
    const int client = ::accept(server_fd, nullptr, nullptr);
    if (client < 0) { if (running.load() && errno != EINTR) log("error", "accept_failed", std::strerror(errno)); continue; }
    timeval timeout{2, 0};
    ::setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    clients.emplace_back(serve_client, client, std::ref(engine));
  }
  if (server_fd >= 0) ::close(server_fd);
  for (auto& client : clients) if (client.joinable()) client.join();
  log("info", "stopped");
}
