// SPDX-License-Identifier: GPL-3.0-only
#include "oni/options.h"
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#ifndef _WIN32
#include <sys/stat.h>
#endif

namespace {
int checks = 0;
void check(bool value, const char *message) { ++checks; if (!value) throw std::runtime_error(message); }
std::string read(const std::filesystem::path &path) { std::ifstream in(path); return {std::istreambuf_iterator<char>(in), {}}; }
}

int main()
{
    const auto root = std::filesystem::temp_directory_path() /
        ("oni-options-test-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    const auto path = root / "oniprofiler.toml";
    try {
        oni::Options expected;
        expected.dashboard_enabled = true;
        expected.dashboard_url = "https://profiler.example";
        expected.dashboard_token = "0123456789abcdefghijklmnopqrstuv";
        expected.dashboard_poll_seconds = 12;
        expected.dashboard_sync_reports = false;
        expected.remote_controls_enabled = true;
        std::string error;
        check(expected.save(path, error), "dashboard config saved");
        const auto text = read(path);
        check(text.find("dashboard_url = \"https://profiler.example\"") != std::string::npos, "origin is quoted");
        check(text.find("dashboard_token = \"0123456789abcdefghijklmnopqrstuv\"") != std::string::npos, "token is quoted");
#ifndef _WIN32
        struct stat info{}; check(::stat(path.c_str(), &info) == 0 && (info.st_mode & 077) == 0, "config is owner only");
#endif
        const auto actual = oni::Options::load(path);
        check(actual.dashboard_enabled && actual.dashboard_url == expected.dashboard_url, "dashboard settings loaded");
        check(actual.dashboard_token == expected.dashboard_token && actual.dashboard_poll_seconds == 12, "token and interval loaded");
        check(!actual.dashboard_sync_reports && actual.remote_controls_enabled, "dashboard booleans loaded");

        { std::ofstream out(path, std::ios::trunc); out << "dashboard_enabled = true\ndashboard_url = \"HTTPS://Profiler.Example/\"\ndashboard_token = \"0123456789abcdefghijklmnopqrstuv\"\n"; }
        check(oni::Options::load(path).dashboard_url == "https://Profiler.Example", "scheme and trailing slash normalized");

        { std::ofstream out(path, std::ios::trunc); out << "dashboard_enabled = true\ndashboard_url = \"http://public.example\"\ndashboard_token = \"0123456789abcdefghijklmnopqrstuv\"\n"; }
        bool rejected = false;
        try { (void)oni::Options::load(path); } catch (const std::runtime_error &) { rejected = true; }
        check(rejected, "insecure origin rejected");
        { std::ofstream out(path, std::ios::trunc); out << "dashboard_enabled = true\ndashboard_url = \"https://profiler.example/path\"\ndashboard_token = \"0123456789abcdefghijklmnopqrstuv\"\n"; }
        rejected = false;
        try { (void)oni::Options::load(path); } catch (const std::runtime_error &) { rejected = true; }
        check(rejected, "origin path rejected");
        { std::ofstream out(path, std::ios::trunc); out << "dashboard_enabled = true\ndashboard_url = \"https://profiler.example\"\ndashboard_token = \"short\"\n"; }
        rejected = false;
        try { (void)oni::Options::load(path); } catch (const std::runtime_error &) { rejected = true; }
        check(rejected, "short token rejected");
        { std::ofstream out(path, std::ios::trunc); out << "background_enabled = false\n"; }
        const auto migrated = oni::Options::load(path);
        check(!migrated.background_enabled && read(path).find("dashboard_enabled = false") != std::string::npos,
              "older managed config gains native dashboard settings");
        std::filesystem::remove_all(root);
        std::cout << checks << " option checks passed\n"; return 0;
    } catch (const std::exception &error) {
        std::filesystem::remove_all(root); std::cerr << error.what() << '\n'; return 1;
    }
}
