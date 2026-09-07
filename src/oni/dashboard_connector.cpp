// SPDX-License-Identifier: GPL-3.0-only
#include "oni/dashboard_connector.h"
#include "oni/bridge_protocol.h"
#include "oni/domain.h"
#include <algorithm>
#include <chrono>
#include <fstream>
#include <functional>
#include <iterator>
#include <stdexcept>
#include <system_error>
#include <utility>
#include <curl/curl.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/stat.h>
#endif

namespace oni {
namespace {
constexpr std::size_t max_snapshot = 2 * 1024 * 1024;

void privateFolder(const std::filesystem::path &path)
{
    if (std::filesystem::is_symlink(path)) throw std::runtime_error("Connector directory must not be a symlink");
    std::filesystem::create_directories(path);
#ifndef _WIN32
    std::filesystem::permissions(path, std::filesystem::perms::owner_all,
                                 std::filesystem::perm_options::replace);
#endif
}

std::string readBounded(const std::filesystem::path &path, std::size_t limit)
{
    if (std::filesystem::is_symlink(path) || !std::filesystem::is_regular_file(path))
        throw std::runtime_error("Connector input is missing or is a symlink");
    const auto size = std::filesystem::file_size(path);
    if (size == 0 || size > limit) throw std::runtime_error("Connector input exceeds its size limit");
    std::ifstream stream(path, std::ios::binary);
    stream.exceptions(std::ios::badbit);
    if (!stream) throw std::runtime_error("Connector input could not be opened");
    std::string data(static_cast<std::size_t>(size), '\0');
    stream.read(data.data(), static_cast<std::streamsize>(data.size()));
    if (stream.gcount() != static_cast<std::streamsize>(data.size()) || stream.peek() != std::char_traits<char>::eof())
        throw std::runtime_error("Connector input changed while it was being read");
    return data;
}

void atomicPrivate(const std::filesystem::path &path, std::string_view data)
{
    privateFolder(path.parent_path());
    auto temporary = path; temporary += ".native-tmp";
    if (std::filesystem::is_symlink(path) || std::filesystem::is_symlink(temporary))
        throw std::runtime_error("Connector mailbox file must not be a symlink");
    std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
    out.exceptions(std::ios::badbit | std::ios::failbit);
    out.write(data.data(), static_cast<std::streamsize>(data.size()));
    out.flush(); out.close();
#ifndef _WIN32
    if (::chmod(temporary.c_str(), S_IRUSR | S_IWUSR) != 0)
        throw std::runtime_error("Could not restrict connector mailbox permissions");
#endif
#ifdef _WIN32
    if (!MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        throw std::runtime_error("Could not replace connector mailbox file");
#else
    std::filesystem::rename(temporary, path);
#endif
}

bool reportName(std::string_view name)
{
    if (name.size() < 13 || name.size() > 112 || !name.starts_with("report-") || !name.ends_with(".json")) return false;
    const auto middle = name.substr(7, name.size() - 12);
    if (middle.empty() || middle.size() > 100) return false;
    for (char c : middle)
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-')) return false;
    return true;
}

std::once_flag curl_once;
void initCurl()
{
    std::call_once(curl_once, [] {
        if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK)
            throw std::runtime_error("Native HTTPS initialization failed");
    });
}

struct CurlHeaders {
    curl_slist *value = nullptr;
    ~CurlHeaders() { curl_slist_free_all(value); }
};
struct CurlEasy {
    CURL *value = curl_easy_init();
    ~CurlEasy() { if (value) curl_easy_cleanup(value); }
};

struct WriteTarget { std::string *body; std::size_t limit; bool exceeded = false; };
std::size_t writeResponse(char *data, std::size_t size, std::size_t count, void *opaque)
{
    auto &target = *static_cast<WriteTarget *>(opaque);
    const auto bytes = size * count;
    if (bytes > target.limit - std::min(target.limit, target.body->size())) {
        target.exceeded = true; return 0;
    }
    target.body->append(data, bytes); return bytes;
}
}

DashboardConnector::DashboardConnector(std::filesystem::path plugin_root, std::string origin,
        std::string token, int poll_seconds, bool sync_reports)
    : root_(std::move(plugin_root)), bridge_(root_ / "bridge"), reports_(root_ / "reports"),
      state_(root_ / "native-dashboard.state"), origin_(std::move(origin)), token_(std::move(token)),
      poll_seconds_(poll_seconds), sync_reports_(sync_reports), thread_([this] { worker(); }) {}

DashboardConnector::~DashboardConnector() { stop(); }
void DashboardConnector::stop()
{
    { std::lock_guard lock(mutex_); stopping_ = true; wake_.notify_all(); }
    if (thread_.joinable()) thread_.join();
}
std::string DashboardConnector::takeError() { std::lock_guard lock(mutex_); return std::exchange(error_, {}); }
std::string DashboardConnector::takeNotice() { std::lock_guard lock(mutex_); return std::exchange(notice_, {}); }

DashboardConnector::Response DashboardConnector::post(std::string_view endpoint, std::string_view body,
                                                       std::size_t response_limit)
{
    initCurl(); CurlEasy easy;
    if (!easy.value) throw std::runtime_error("Native HTTPS request could not be created");
    Response response; WriteTarget target{&response.body, response_limit};
    CurlHeaders headers;
    const std::string authorization = "Authorization: Bearer " + token_;
    headers.value = curl_slist_append(headers.value, authorization.c_str());
    headers.value = curl_slist_append(headers.value, "Content-Type: application/json");
    headers.value = curl_slist_append(headers.value, "Accept: application/x-oniprofiler-commands, text/plain");
    headers.value = curl_slist_append(headers.value, "Expect:");
    const std::string url = origin_ + std::string(endpoint);
    curl_easy_setopt(easy.value, CURLOPT_URL, url.c_str());
    curl_easy_setopt(easy.value, CURLOPT_HTTPHEADER, headers.value);
    curl_easy_setopt(easy.value, CURLOPT_POST, 1L);
    curl_easy_setopt(easy.value, CURLOPT_POSTFIELDS, body.data());
    curl_easy_setopt(easy.value, CURLOPT_POSTFIELDSIZE_LARGE, static_cast<curl_off_t>(body.size()));
    curl_easy_setopt(easy.value, CURLOPT_WRITEFUNCTION, writeResponse);
    curl_easy_setopt(easy.value, CURLOPT_WRITEDATA, &target);
    curl_easy_setopt(easy.value, CURLOPT_CONNECTTIMEOUT_MS, 5000L);
    curl_easy_setopt(easy.value, CURLOPT_TIMEOUT_MS, 12000L);
    curl_easy_setopt(easy.value, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(easy.value, CURLOPT_FOLLOWLOCATION, 0L);
    curl_easy_setopt(easy.value, CURLOPT_PROTOCOLS_STR, "https");
    curl_easy_setopt(easy.value, CURLOPT_REDIR_PROTOCOLS_STR, "https");
    curl_easy_setopt(easy.value, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(easy.value, CURLOPT_SSL_VERIFYHOST, 2L);
    curl_easy_setopt(easy.value, CURLOPT_SSLVERSION, CURL_SSLVERSION_TLSv1_2);
    const std::string user_agent = "OniProfiler-native/" + std::string(version);
    curl_easy_setopt(easy.value, CURLOPT_USERAGENT, user_agent.c_str());
    const auto result = curl_easy_perform(easy.value);
    if (result != CURLE_OK) {
        if (target.exceeded) throw std::runtime_error("Dashboard response exceeded its size limit");
        throw std::runtime_error(std::string("Dashboard HTTPS request failed: ") + curl_easy_strerror(result));
    }
    curl_easy_getinfo(easy.value, CURLINFO_RESPONSE_CODE, &response.status);
    return response;
}

void DashboardConnector::deliver(std::string_view response)
{
    privateFolder(bridge_); privateFolder(bridge_ / "inbox");
    for (const auto &wire : splitNativeCommands(response)) {
        std::string error; const auto command = parseRemote(wire, error);
        if (!command) throw std::runtime_error("Dashboard command failed validation: " + error);
        const auto filename = command->id + ".cmd";
        if (std::filesystem::exists(bridge_ / "claimed" / filename) ||
            std::filesystem::exists(bridge_ / "outbox" / (command->id + ".json")) ||
            std::filesystem::exists(bridge_ / "inbox" / filename)) continue;
        atomicPrivate(bridge_ / "inbox" / filename, wire);
    }
}

void DashboardConnector::acknowledge()
{
    const auto folder = bridge_ / "outbox";
    if (!std::filesystem::is_directory(folder) || std::filesystem::is_symlink(folder)) return;
    std::set<std::string> present; std::size_t sent = 0, scanned = 0; bool changed = false;
    for (const auto &entry : std::filesystem::directory_iterator(folder)) {
        if (++scanned > 4096) break;
        if (entry.is_symlink() || !entry.is_regular_file() || entry.path().extension() != ".json") continue;
        const auto id = entry.path().stem().string(); if (!bridgeId(id)) continue;
        present.insert(id); if (sent_acks_.contains(id) || sent >= 16) continue;
        const auto body = readBounded(entry.path(), 16384);
        const auto response = post("/api/agent/ack", body, 4096);
        if ((response.status < 200 || response.status >= 300) && response.status != 404)
            throw std::runtime_error("Dashboard rejected a command receipt: HTTP " + std::to_string(response.status));
        sent_acks_.insert(id); ++sent; changed = true;
    }
    changed = std::erase_if(sent_acks_, [&](const auto &id) { return !present.contains(id); }) > 0 || changed;
    if (changed) saveState();
}

void DashboardConnector::reports()
{
    if (!sync_reports_ || !std::filesystem::is_directory(reports_) || std::filesystem::is_symlink(reports_)) return;
    std::vector<std::filesystem::path> paths; std::size_t scanned = 0;
    for (const auto &entry : std::filesystem::directory_iterator(reports_)) {
        if (++scanned > 4096) throw std::runtime_error("Report directory exceeds the connector scan limit");
        if (!entry.is_symlink() && entry.is_regular_file() && reportName(entry.path().filename().string())) paths.push_back(entry.path());
    }
    std::ranges::sort(paths, std::greater{});
    std::set<std::string> present; std::size_t sent = 0; bool changed = false;
    for (const auto &path : paths) {
        const auto name = path.filename().string(); present.insert(name);
        if (sent_reports_.contains(name) || sent >= 4) continue;
        const auto body = readBounded(path, max_snapshot);
        const auto response = post("/api/native/report/" + name, body, 4096);
        if (response.status < 200 || response.status >= 300)
            throw std::runtime_error("Dashboard rejected a report: HTTP " + std::to_string(response.status));
        sent_reports_.insert(name); ++sent; changed = true;
    }
    changed = std::erase_if(sent_reports_, [&](const auto &name) { return !present.contains(name); }) > 0 || changed;
    if (changed) saveState();
}

void DashboardConnector::loadState()
{
    if (!std::filesystem::exists(state_)) return;
    const auto data = readBounded(state_, 256 * 1024); std::size_t start = 0, lines = 0;
    while (start < data.size() && ++lines <= 4096) {
        auto end = data.find('\n', start); if (end == std::string::npos) end = data.size();
        const std::string_view line(data.data() + start, end - start);
        if (line.starts_with("A:") && bridgeId(line.substr(2))) sent_acks_.emplace(line.substr(2));
        else if (line.starts_with("R:") && reportName(line.substr(2))) sent_reports_.emplace(line.substr(2));
        start = end + 1;
    }
}

void DashboardConnector::saveState()
{
    std::string data;
    for (const auto &id : sent_acks_) data += "A:" + id + '\n';
    for (const auto &name : sent_reports_) data += "R:" + name + '\n';
    atomicPrivate(state_, data.empty() ? "#\n" : data);
}

bool DashboardConnector::cycle()
{
    acknowledge();
    const auto dashboard = reports_ / "dashboard.json";
    if (!std::filesystem::exists(dashboard)) return false;
    const auto snapshot = readBounded(dashboard, max_snapshot);
    const auto response = post("/api/native/heartbeat", snapshot, 32768);
    if (response.status < 200 || response.status >= 300)
        throw std::runtime_error("Dashboard rejected the native heartbeat: HTTP " + std::to_string(response.status));
    deliver(response.body); reports(); return true;
}

void DashboardConnector::worker() noexcept
{
    try { privateFolder(root_); loadState(); }
    catch (const std::exception &e) { std::lock_guard lock(mutex_); error_ = e.what(); return; }
    {
        std::unique_lock lock(mutex_);
        wake_.wait_for(lock, std::chrono::seconds(poll_seconds_), [&] { return stopping_; });
        if (stopping_) return;
    }
    unsigned failures = 0; bool announced = false; std::string previous_error;
    for (;;) {
        { std::lock_guard lock(mutex_); if (stopping_) break; }
        try {
            const bool connected = cycle(); failures = 0; previous_error.clear();
            if (connected && !announced) { std::lock_guard lock(mutex_); notice_ = "Native dashboard link connected; no game-server wheel or agent process is required."; announced = true; }
        } catch (const std::exception &e) {
            ++failures;
            if (previous_error != e.what()) { std::lock_guard lock(mutex_); error_ = e.what(); previous_error = e.what(); }
            announced = false;
        }
        const auto multiplier = 1u << std::min(failures, 3u);
        std::unique_lock lock(mutex_);
        wake_.wait_for(lock, std::chrono::seconds(std::min(60u, static_cast<unsigned>(poll_seconds_) * multiplier)),
                       [&] { return stopping_; });
        if (stopping_) break;
    }
}
}
