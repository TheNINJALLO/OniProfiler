// SPDX-License-Identifier: GPL-3.0-only
#pragma once
#include "oni/bridge_protocol.h"
#include <condition_variable>
#include <filesystem>
#include <mutex>
#include <set>
#include <string>
#include <string_view>
#include <stdexcept>
#include <thread>
#include <vector>

namespace oni {
inline constexpr std::string_view nativeCommandSeparator = "\n--oniprofiler-command--\n";

// Splits the bounded native endpoint response. Each item is validated again by
// CommandBridge before any action reaches the server thread.
inline std::vector<std::string> splitNativeCommands(std::string_view response)
{
    constexpr std::size_t max_commands = 4;
    std::vector<std::string> result;
    if (response.empty()) return result;
    while (true) {
        const auto split = response.find(nativeCommandSeparator);
        const auto item = response.substr(0, split);
        if (item.empty() || result.size() >= max_commands)
            throw std::runtime_error("Dashboard returned an invalid command batch");
        std::string error;
        if (!parseRemote(item, error)) throw std::runtime_error("Dashboard returned an invalid command: " + error);
        result.emplace_back(item);
        if (split == std::string_view::npos) break;
        response.remove_prefix(split + nativeCommandSeparator.size());
    }
    return result;
}

// Outbound HTTPS and local mailbox I/O only. This worker never receives an
// Endstone object, player, chunk, world, scheduler, logger, or command sender.
class DashboardConnector {
public:
    DashboardConnector(std::filesystem::path plugin_root, std::string origin,
                       std::string token, int poll_seconds, bool sync_reports);
    ~DashboardConnector();
    DashboardConnector(const DashboardConnector &) = delete;
    DashboardConnector &operator=(const DashboardConnector &) = delete;
    void stop();
    std::string takeError();
    std::string takeNotice();
private:
    struct Response { long status = 0; std::string body; };
    void worker() noexcept;
    bool cycle();
    Response post(std::string_view endpoint, std::string_view body, std::size_t response_limit);
    void deliver(std::string_view response);
    void acknowledge();
    void reports();
    void loadState();
    void saveState();
    std::filesystem::path root_, bridge_, reports_, state_;
    std::string origin_, token_;
    int poll_seconds_;
    bool sync_reports_;
    std::set<std::string> sent_acks_, sent_reports_;
    std::mutex mutex_;
    std::condition_variable wake_;
    std::string error_, notice_;
    bool stopping_ = false;
    std::thread thread_;
};
}
