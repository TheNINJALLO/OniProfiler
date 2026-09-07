// SPDX-License-Identifier: GPL-3.0-only
// OniProfiler additions, 2026. Native profiling is provided by EndstoneMC/spark.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <locale>
#include <cstddef>
#include <map>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace oni {
inline constexpr char version[] = "1.0.1";
inline constexpr char upstream_commit[] = "8958173ad40c1da9adf3254305526443c9853848";

inline std::string quote(std::string_view value)
{
    std::ostringstream out;
    out << '"';
    for (unsigned char c : value) {
        switch (c) {
        case '"': out << "\\\""; break;
        case '\\': out << "\\\\"; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (c < 0x20) {
                out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(c) << std::dec;
            } else { out << static_cast<char>(c); }
        }
    }
    out << '"';
    return out.str();
}

inline std::string number(std::optional<double> value)
{
    if (!value || !std::isfinite(*value)) return "null";
    std::ostringstream out;
    out.imbue(std::locale::classic());
    out << std::setprecision(12) << *value;
    return out.str();
}

inline std::string fixed(std::optional<double> value, int precision = 1)
{
    if (!value || !std::isfinite(*value)) return "Unavailable";
    std::ostringstream out;
    out.imbue(std::locale::classic());
    out << std::fixed << std::setprecision(precision) << *value;
    return out.str();
}

struct Health {
    std::int64_t timestamp_ms = 0;
    std::int64_t history_ms = 0;
    std::int64_t tps_span_ms = 0;
    std::int64_t mspt_span_ms = 0;
    std::int64_t cpu_span_ms = 0;
    std::size_t tick_samples = 0;
    std::optional<double> tps, mspt_mean, mspt_p95, mspt_max, cpu_percent, rss_bytes;
    std::int64_t players = 0;
    std::optional<std::int64_t> entities, chunks;
};

struct Finding { std::string level, evidence, title, detail; };

inline std::vector<Finding> explain(const Health &h)
{
    std::vector<Finding> out;
    if (h.history_ms < 10000 || h.tick_samples < 20 || !h.tps || !h.mspt_mean
        || !std::isfinite(*h.tps) || !std::isfinite(*h.mspt_mean)) {
        out.push_back({"unknown", "measured", "Collecting a useful baseline",
                       "Less than 10 seconds or too few valid tick samples are available. Do not grade this as healthy yet."});
        return out;
    }
    if (*h.tps < 18.0 || *h.mspt_mean > 50.0) {
        out.push_back({"critical", "measured", "Simulation is struggling",
                       "TPS is below 18 or mean tick duration exceeds the 50 ms target budget. Record a profile while the problem is occurring."});
    } else if (*h.tps < 19.5 || (h.mspt_p95 && *h.mspt_p95 > 50.0)) {
        out.push_back({"warning", "measured", "Some ticks exceed the target budget",
                       "TPS is below 19.5 or the 95th-percentile tick duration exceeds 50 ms. Compare another recording under a similar workload."});
    } else {
        out.push_back({"ok", "measured", "Recent tick measurements are within the selected thresholds",
                       "This is a rolling measurement, not proof that every farm, player connection, or earlier period is healthy."});
    }
    if (h.mspt_max && *h.mspt_max > 250.0) {
        out.push_back({"warning", "measured", "A long tick occurred",
                       "The longest tick in the displayed window exceeded 250 ms. A maximum alone does not identify the cause or frequency."});
    }
    if (h.cpu_percent) {
        out.push_back({"info", "limitation", "CPU percentage uses total host capacity",
                       "A low process percentage can hide one saturated server thread. This is not your Pterodactyl CPU-allocation percentage."});
    }
    if (h.rss_bytes) {
        out.push_back({"info", "limitation", "Memory shown is resident process memory",
                       "No container memory limit is inferred. One reading cannot establish a memory leak."});
    }
    return out;
}

inline std::string healthJson(const Health &h)
{
    std::ostringstream o;
    o << "{\"timestamp_ms\":" << h.timestamp_ms << ",\"history_ms\":" << h.history_ms
      << ",\"tps_span_ms\":" << h.tps_span_ms << ",\"mspt_span_ms\":" << h.mspt_span_ms
      << ",\"cpu_span_ms\":" << h.cpu_span_ms << ",\"tick_samples\":" << h.tick_samples
      << ",\"tps\":" << number(h.tps) << ",\"mspt_mean\":" << number(h.mspt_mean)
      << ",\"mspt_p95\":" << number(h.mspt_p95) << ",\"mspt_max\":" << number(h.mspt_max)
      << ",\"cpu_percent\":" << number(h.cpu_percent) << ",\"rss_bytes\":" << number(h.rss_bytes)
      << ",\"players\":" << h.players << ",\"entities\":";
    if (h.entities) o << *h.entities; else o << "null";
    o << ",\"chunks\":";
    if (h.chunks) o << *h.chunks; else o << "null";
    o << '}';
    return o.str();
}

inline std::string findingsJson(const Health &h)
{
    std::string s = "[";
    for (const auto &f : explain(h)) {
        if (s.size() > 1) s += ',';
        s += "{\"level\":" + quote(f.level) + ",\"evidence\":" + quote(f.evidence)
             + ",\"title\":" + quote(f.title) + ",\"detail\":" + quote(f.detail) + '}';
    }
    return s + ']';
}

struct Area {
    std::string dimension;
    int chunk_x = 0, chunk_z = 0;
    std::int64_t entities = 0;
    std::map<std::string, int> types;
};

inline void rankAreas(std::vector<Area> &areas, std::size_t limit)
{
    const auto less = [](const Area &a, const Area &b) {
        if (a.entities != b.entities) return a.entities > b.entities;
        if (a.dimension != b.dimension) return a.dimension < b.dimension;
        if (a.chunk_x != b.chunk_x) return a.chunk_x < b.chunk_x;
        return a.chunk_z < b.chunk_z;
    };
    const auto count = std::min(limit, areas.size());
    std::partial_sort(areas.begin(), areas.begin() + static_cast<std::ptrdiff_t>(count), areas.end(), less);
    areas.resize(count);
}

inline std::string areasJson(const std::vector<Area> &areas, std::int64_t snapshot_ms)
{
    std::string s = "{\"snapshot_ms\":" + std::to_string(snapshot_ms)
        + ",\"scope\":\"Loaded chunks only; ranked by entity count, not measured tick cost\",\"areas\":[";
    bool first = true;
    for (const auto &a : areas) {
        if (!first) s += ',';
        first = false;
        s += "{\"dimension\":" + quote(a.dimension) + ",\"chunk_x\":" + std::to_string(a.chunk_x)
           + ",\"chunk_z\":" + std::to_string(a.chunk_z) + ",\"entities\":" + std::to_string(a.entities)
           + ",\"types\":{";
        bool first_type = true;
        for (const auto &[name, count] : a.types) {
            if (!first_type) s += ',';
            first_type = false;
            s += quote(name) + ':' + std::to_string(count);
        }
        s += "}}";
    }
    return s + "]}";
}

// No allocations on the tick path. Requires consecutive slow observations;
// a healthy or invalid tick resets the sustained period, but not the cooldown.
class IncidentDetector {
public:
    double threshold_ms = 100.0;
    std::int64_t sustain_ms = 5000;
    std::int64_t cooldown_ms = 300000;

    bool observe(double tick_ms, std::int64_t steady_ms)
    {
        if (previous_ && steady_ms < *previous_) { since_.reset(); last_trigger_.reset(); }
        previous_ = steady_ms;
        if (!std::isfinite(tick_ms) || tick_ms < threshold_ms) { since_.reset(); return false; }
        if (!since_) since_ = steady_ms;
        if (steady_ms - *since_ < sustain_ms) return false;
        if (last_trigger_ && steady_ms - *last_trigger_ < cooldown_ms) return false;
        last_trigger_ = steady_ms;
        since_ = steady_ms;
        return true;
    }
    void reset() { since_.reset(); previous_.reset(); }
private:
    std::optional<std::int64_t> since_, last_trigger_, previous_;
};

inline bool mayControl(const std::string &actor, const std::string &owner, bool record_permission,
                       bool manage_permission, std::int64_t expected_session, std::int64_t actual_session)
{
    return expected_session == actual_session && actual_session > 0
        && (manage_permission || (record_permission && !owner.empty() && actor == owner));
}

struct AdvancedPolicy { bool external = false, starts = false, mutates = false, force_local = false; };
inline AdvancedPolicy classifyAdvanced(const std::vector<std::string> &tokens)
{
    const auto has = [&](const std::string &flag) {
        return std::any_of(tokens.begin(), tokens.end(), [&](const std::string &value) {
            return value == flag || value.starts_with(flag + "=");
        });
    };
    AdvancedPolicy policy;
    policy.external = has("--upload");
    if (tokens.size() < 2 || (tokens[0] != "profiler" && tokens[0] != "sampler")) return policy;
    policy.external = policy.external || tokens[1] == "open" || tokens[1] == "trust-viewer";
    policy.starts = tokens[1] == "start";
    policy.mutates = tokens[1] == "stop" || tokens[1] == "upload" || tokens[1] == "cancel"
        || tokens[1] == "open" || tokens[1] == "trust-viewer" || has("--stop") || has("--upload");
    policy.force_local = policy.starts || tokens[1] == "stop" || tokens[1] == "upload" || has("--stop") || has("--upload");
    return policy;
}

struct Preset { std::string key, title; int seconds, interval_ms, only_over_ms; bool allocation; };
inline const std::vector<Preset> &presets()
{
    static const std::vector<Preset> values = {
        {"quick", "Quick investigation", 30, 4, 0, false},
        {"lag", "Server is lagging now", 60, 4, 0, false},
        {"spikes", "Occasional freezes", 180, 4, 50, false},
        {"memory", "Native allocation investigation", 60, 0, 0, true}
    };
    return values;
}

inline std::vector<std::string> presetTokens(const Preset &p, const std::string &comment)
{
    std::vector<std::string> out = {"start", "--timeout", std::to_string(p.seconds), "--save-to-file", "--comment", comment};
    if (p.allocation) out.push_back("--alloc");
    else { out.push_back("--interval"); out.push_back(std::to_string(p.interval_ms)); }
    if (p.only_over_ms > 0) { out.push_back("--only-ticks-over"); out.push_back(std::to_string(p.only_over_ms)); }
    return out;
}
} // namespace oni
