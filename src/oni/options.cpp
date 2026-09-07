// SPDX-License-Identifier: GPL-3.0-only
#include "oni/options.h"
#include <algorithm>
#include <cctype>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <toml++/toml.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/stat.h>
#endif
namespace oni {
namespace {
std::string origin(std::string value)
{
    if (value.empty()) return value;
    if (value.size() > 2048 || value.size() < 8)
        throw std::runtime_error("dashboard_url must be an HTTPS origin");
    std::string scheme = value.substr(0, 8);
    std::ranges::transform(scheme, scheme.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (scheme != "https://") throw std::runtime_error("dashboard_url must be an HTTPS origin");
    value.replace(0, 8, "https://");
    if (value.size() > 8 && value.ends_with('/')) value.pop_back();
    const auto authority = value.substr(8);
    if (authority.empty() || authority.find_first_of("/?#@") != std::string::npos)
        throw std::runtime_error("dashboard_url must not contain credentials, a path, query, or fragment");
    for (unsigned char c : value)
        if (c <= 0x20 || c == 0x7f) throw std::runtime_error("dashboard_url contains invalid whitespace");
    for (const char c : authority)
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
              c == '.' || c == '-' || c == ':' || c == '[' || c == ']'))
            throw std::runtime_error("dashboard_url contains an invalid hostname or port");
    return value;
}
bool token(std::string_view value)
{
    if (value.size() < 20 || value.size() > 128) return false;
    for (const char c : value)
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '_' || c == '-')) return false;
    return true;
}
}
Options Options::load(const std::filesystem::path &path)
{
    Options o;
    if (!std::filesystem::exists(path)) {
        std::string error;
        if (!o.save(path, error)) throw std::runtime_error(error);
        return o;
    }
    if (std::filesystem::is_symlink(path))
        throw std::runtime_error("Refusing to read an OniProfiler configuration symlink");
#ifndef _WIN32
    if (::chmod(path.c_str(), S_IRUSR | S_IWUSR) != 0)
        throw std::runtime_error("Could not restrict OniProfiler configuration permissions");
#endif
    const auto t = toml::parse_file(path.string());
    auto boolean = [&](const char *key, bool &value) {
        if (t.contains(key)) {
            auto read = t[key].value<bool>();
            if (!read) throw std::runtime_error(std::string(key) + " must be true or false");
            value = *read;
        }
    };
    auto integer = [&](const char *key, int &value, int low, int high) {
        if (t.contains(key)) {
            auto read = t[key].value<std::int64_t>();
            if (!read || *read < low || *read > high)
                throw std::runtime_error(std::string(key) + " must be between " + std::to_string(low) + " and " + std::to_string(high));
            value = static_cast<int>(*read);
        }
    };
    auto text = [&](const char *key, std::string &value) {
        if (t.contains(key)) {
            auto read = t[key].value<std::string>();
            if (!read) throw std::runtime_error(std::string(key) + " must be a string");
            value = *read;
        }
    };
    boolean("background_enabled", o.background_enabled);
    boolean("dashboard_enabled", o.dashboard_enabled);
    boolean("dashboard_sync_reports", o.dashboard_sync_reports);
    boolean("remote_controls_enabled", o.remote_controls_enabled);
    boolean("remote_management_enabled", o.remote_management_enabled);
    boolean("incidents_enabled", o.incidents_enabled);
    boolean("automatic_profiles", o.automatic_profiles);
    boolean("allow_external_sharing", o.allow_external_sharing);
    text("dashboard_url", o.dashboard_url);
    text("dashboard_token", o.dashboard_token);
    o.dashboard_url = origin(o.dashboard_url);
    if (!o.dashboard_token.empty() && !token(o.dashboard_token))
        throw std::runtime_error("dashboard_token must be the 20-128 character key created by the dashboard");
    if (o.dashboard_enabled && (o.dashboard_url.empty() || !token(o.dashboard_token)))
        throw std::runtime_error("dashboard_enabled requires dashboard_url and dashboard_token");
    integer("dashboard_poll_seconds", o.dashboard_poll_seconds, 5, 60);
    integer("refresh_seconds", o.refresh_seconds, 5, 60);
    integer("area_cooldown_seconds", o.area_cooldown_seconds, 30, 3600);
    integer("max_areas", o.max_areas, 10, 1000);
    integer("retained_summaries", o.retained_summaries, 10, 1000);
    integer("automatic_storage_limit_mb", o.automatic_storage_limit_mb, 32, 16384);
    integer("incident_threshold_ms", o.incident_threshold_ms, 50, 5000);
    integer("incident_sustain_seconds", o.incident_sustain_seconds, 1, 120);
    integer("incident_cooldown_seconds", o.incident_cooldown_seconds, 60, 86400);
    if (!t.contains("dashboard_enabled") || !t.contains("dashboard_url") ||
        !t.contains("dashboard_token") || !t.contains("dashboard_poll_seconds") ||
        !t.contains("dashboard_sync_reports")) {
        std::string error;
        if (!o.save(path, error)) throw std::runtime_error("Could not add native dashboard settings: " + error);
    }
    return o;
}
bool Options::save(const std::filesystem::path &path, std::string &error) const
{
    try {
        std::filesystem::create_directories(path.parent_path());
        auto temporary = path; temporary += ".tmp";
        if (std::filesystem::is_symlink(path) || std::filesystem::is_symlink(temporary))
            throw std::runtime_error("Refusing to overwrite a configuration symlink");
        std::ofstream out(temporary, std::ios::trunc);
        out.exceptions(std::ios::badbit | std::ios::failbit);
        out << "# OniProfiler powered by spark\n# Values are validated on startup. Restart after editing.\n"
            << "# UI setting changes rewrite this managed file; Spark's config.toml stays separate.\n"
            << "# Native dashboard link: no Python wheel or agent process is needed on this game server.\n"
            << "# Treat dashboard_token as a password. Create or rotate it in the dashboard.\n"
            << std::boolalpha
            << "dashboard_enabled = " << dashboard_enabled << '\n'
            << "dashboard_url = \"" << dashboard_url << "\"\n"
            << "dashboard_token = \"" << dashboard_token << "\"\n"
            << "dashboard_poll_seconds = " << dashboard_poll_seconds << '\n'
            << "dashboard_sync_reports = " << dashboard_sync_reports << '\n'
            << "remote_controls_enabled = " << remote_controls_enabled << '\n'
            << "remote_management_enabled = " << remote_management_enabled << '\n'
            << "background_enabled = " << background_enabled << '\n'
            << "incidents_enabled = " << incidents_enabled << '\n'
            << "automatic_profiles = " << automatic_profiles << '\n'
            << "allow_external_sharing = " << allow_external_sharing << '\n'
            << "refresh_seconds = " << refresh_seconds << '\n'
            << "area_cooldown_seconds = " << area_cooldown_seconds << '\n'
            << "max_areas = " << max_areas << '\n'
            << "retained_summaries = " << retained_summaries << '\n'
            << "automatic_storage_limit_mb = " << automatic_storage_limit_mb << '\n'
            << "incident_threshold_ms = " << incident_threshold_ms << '\n'
            << "incident_sustain_seconds = " << incident_sustain_seconds << '\n'
            << "incident_cooldown_seconds = " << incident_cooldown_seconds << '\n';
        out.flush(); out.close();
#ifdef _WIN32
        if (!MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
            throw std::runtime_error("Could not replace OniProfiler configuration");
#else
        std::filesystem::rename(temporary, path);
        if (::chmod(path.c_str(), S_IRUSR | S_IWUSR) != 0)
            throw std::runtime_error("Could not restrict OniProfiler configuration permissions");
#endif
        return true;
    } catch (const std::exception &e) { error = e.what(); return false; }
}
}
