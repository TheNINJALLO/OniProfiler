// SPDX-License-Identifier: GPL-3.0-only
#include "oni/options.h"
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <toml++/toml.h>
#ifdef _WIN32
#include <windows.h>
#endif
namespace oni {
Options Options::load(const std::filesystem::path &path)
{
    Options o;
    if (!std::filesystem::exists(path)) {
        std::string error;
        if (!o.save(path, error)) throw std::runtime_error(error);
        return o;
    }
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
    boolean("background_enabled", o.background_enabled);
    boolean("remote_controls_enabled", o.remote_controls_enabled);
    boolean("remote_management_enabled", o.remote_management_enabled);
    boolean("incidents_enabled", o.incidents_enabled);
    boolean("automatic_profiles", o.automatic_profiles);
    boolean("allow_external_sharing", o.allow_external_sharing);
    integer("refresh_seconds", o.refresh_seconds, 5, 60);
    integer("area_cooldown_seconds", o.area_cooldown_seconds, 30, 3600);
    integer("max_areas", o.max_areas, 10, 1000);
    integer("retained_summaries", o.retained_summaries, 10, 1000);
    integer("automatic_storage_limit_mb", o.automatic_storage_limit_mb, 32, 16384);
    integer("incident_threshold_ms", o.incident_threshold_ms, 50, 5000);
    integer("incident_sustain_seconds", o.incident_sustain_seconds, 1, 120);
    integer("incident_cooldown_seconds", o.incident_cooldown_seconds, 60, 86400);
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
            << std::boolalpha
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
#endif
        return true;
    } catch (const std::exception &e) { error = e.what(); return false; }
}
}
