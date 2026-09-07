// SPDX-License-Identifier: GPL-3.0-only
#pragma once
#include <filesystem>
#include <string>
namespace oni {
struct Options {
    bool background_enabled = true;
    bool remote_controls_enabled = false;
    bool remote_management_enabled = false;
    bool incidents_enabled = true;
    bool automatic_profiles = false;
    bool allow_external_sharing = false;
    int refresh_seconds = 5;
    int area_cooldown_seconds = 60;
    int max_areas = 200;
    int retained_summaries = 100;
    int automatic_storage_limit_mb = 256;
    int incident_threshold_ms = 100;
    int incident_sustain_seconds = 5;
    int incident_cooldown_seconds = 300;
    static Options load(const std::filesystem::path &path);
    bool save(const std::filesystem::path &path, std::string &error) const;
};
}
