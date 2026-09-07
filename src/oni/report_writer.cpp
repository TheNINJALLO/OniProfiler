// SPDX-License-Identifier: GPL-3.0-only
#include "oni/report_writer.h"
#include <algorithm>
#include <chrono>
#include <fstream>
#include <stdexcept>
#include <system_error>
#include <vector>
#include <utility>
#ifdef _WIN32
#include <windows.h>
#endif

namespace oni {
ReportWriter::ReportWriter(std::filesystem::path directory, std::size_t retained)
    : directory_(std::move(directory)), retained_(std::clamp<std::size_t>(retained, 10, 1000)),
      thread_([this] { run(); }) {}
ReportWriter::~ReportWriter() { stop(); }
bool ReportWriter::validId(const std::string &id)
{
    if (id.empty() || id.size() > 80) return false;
    return std::all_of(id.begin(), id.end(), [](unsigned char c) {
        return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || c == '-';
    });
}
void ReportWriter::dashboard(std::string json)
{
    std::lock_guard lock(mutex_);
    if (!stopping_) { dashboard_ = std::move(json); wake_.notify_one(); }
}
bool ReportWriter::report(std::string id, std::string json)
{
    if (!validId(id)) return false;
    std::lock_guard lock(mutex_);
    if (stopping_ || reports_.size() >= 32) return false;
    reports_.emplace_back(std::move(id), std::move(json));
    wake_.notify_one();
    return true;
}
std::string ReportWriter::takeError()
{
    std::lock_guard lock(mutex_);
    return std::exchange(error_, {});
}
void ReportWriter::stop()
{
    { std::lock_guard lock(mutex_); stopping_ = true; wake_.notify_all(); }
    if (thread_.joinable()) thread_.join();
}
void ReportWriter::writeAtomic(const std::filesystem::path &destination, const std::string &data)
{
    std::filesystem::create_directories(destination.parent_path());
    auto temporary = destination;
    temporary += ".tmp";
    // Symlinks in an owner-writable data folder should not redirect report writes.
    if (std::filesystem::is_symlink(temporary) || std::filesystem::is_symlink(destination))
        throw std::runtime_error("Refusing to write through a report symlink");
    {
        std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
        out.exceptions(std::ios::badbit | std::ios::failbit);
        out.write(data.data(), static_cast<std::streamsize>(data.size()));
        out.flush();
        out.close();
    }
#ifdef _WIN32
    if (!MoveFileExW(temporary.c_str(), destination.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), "Replacing report");
#else
    std::filesystem::rename(temporary, destination);
#endif
}
void ReportWriter::prune()
{
    std::vector<std::filesystem::path> files;
    for (const auto &e : std::filesystem::directory_iterator(directory_)) {
        const auto name = e.path().filename().string();
        if (e.is_regular_file() && !e.is_symlink() && name.starts_with("report-")
            && e.path().extension() == ".json" && validId(e.path().stem().string())) files.push_back(e.path());
    }
    std::sort(files.begin(), files.end());
    while (files.size() > retained_) { std::filesystem::remove(files.front()); files.erase(files.begin()); }
}
void ReportWriter::measureProfiles()
{
    std::uint64_t bytes = 0;
    const auto profiles = directory_.parent_path() / "profiles";
    if (std::filesystem::exists(profiles)) {
        for (const auto &e : std::filesystem::directory_iterator(profiles)) {
            if (!e.is_symlink() && e.is_regular_file()) bytes += e.file_size();
        }
    }
    profile_bytes_.store(bytes);
    disk_measured_.store(true);
}
void ReportWriter::run() noexcept
{
    auto next_measure = std::chrono::steady_clock::time_point::min();
    for (;;) {
        std::optional<std::string> dashboard;
        std::deque<std::pair<std::string, std::string>> reports;
        bool stopping;
        {
            std::unique_lock lock(mutex_);
            wake_.wait_for(lock, std::chrono::seconds(10), [this] { return stopping_ || dashboard_ || !reports_.empty(); });
            dashboard.swap(dashboard_); reports.swap(reports_); stopping = stopping_;
        }
        try {
            for (const auto &[id, json] : reports) writeAtomic(directory_ / ("report-" + id + ".json"), json);
            if (!reports.empty()) prune();
            if (dashboard) writeAtomic(directory_ / "dashboard.json", *dashboard);
            if (std::chrono::steady_clock::now() >= next_measure) {
                measureProfiles(); next_measure = std::chrono::steady_clock::now() + std::chrono::seconds(60);
            }
        } catch (const std::exception &e) { std::lock_guard lock(mutex_); error_ = e.what(); }
          catch (...) { std::lock_guard lock(mutex_); error_ = "Unknown report writer failure"; }
        if (stopping) return;
    }
}
}
