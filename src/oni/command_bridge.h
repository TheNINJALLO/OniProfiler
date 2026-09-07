// SPDX-License-Identifier: GPL-3.0-only
#pragma once
#include "oni/bridge_protocol.h"
#include <condition_variable>
#include <deque>
#include <filesystem>
#include <mutex>
#include <string>
#include <thread>
namespace oni {
// The worker handles disk I/O only. The server thread exclusively executes actions.
class CommandBridge {
public:
    explicit CommandBridge(std::filesystem::path root);
    ~CommandBridge();
    CommandBridge(const CommandBridge &) = delete;
    CommandBridge &operator=(const CommandBridge &) = delete;
    std::optional<RemoteCommand> pop();
    void acknowledge(std::string id, std::string status, std::string message, std::int64_t session = 0);
    std::string takeError();
    void stop();
private:
    void worker() noexcept;
    void scan();
    void flush();
    void recover();
    void prune();
    struct Ack { std::string id, status, message; std::int64_t session; };
    std::filesystem::path root_;
    std::mutex mutex_;
    std::condition_variable wake_;
    std::deque<RemoteCommand> incoming_;
    std::deque<Ack> outgoing_;
    std::string error_;
    bool stopping_ = false;
    bool failed_ = false;
    std::thread thread_;
};
}
