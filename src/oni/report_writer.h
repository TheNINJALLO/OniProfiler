// SPDX-License-Identifier: GPL-3.0-only
#pragma once
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <mutex>
#include <optional>
#include <string>
#include <thread>

namespace oni {
// Owns one worker. Only immutable strings cross the main-thread boundary.
class ReportWriter {
public:
    explicit ReportWriter(std::filesystem::path directory, std::size_t retained = 100);
    ~ReportWriter();
    ReportWriter(const ReportWriter &) = delete;
    ReportWriter &operator=(const ReportWriter &) = delete;
    void dashboard(std::string json);
    bool report(std::string id, std::string json);
    std::string takeError();
    void stop();
    std::uint64_t profileBytes() const { return profile_bytes_.load(); }
    bool diskMeasured() const { return disk_measured_.load(); }
    static bool validId(const std::string &id);
private:
    void run() noexcept;
    void writeAtomic(const std::filesystem::path &destination, const std::string &data);
    void prune();
    void measureProfiles();
    std::filesystem::path directory_;
    std::size_t retained_;
    std::mutex mutex_;
    std::condition_variable wake_;
    std::deque<std::pair<std::string, std::string>> reports_;
    std::optional<std::string> dashboard_;
    std::string error_;
    bool stopping_ = false;
    std::atomic<std::uint64_t> profile_bytes_{0};
    std::atomic<bool> disk_measured_{false};
    std::thread thread_;
};
}
