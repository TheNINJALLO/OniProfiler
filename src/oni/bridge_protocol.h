// SPDX-License-Identifier: GPL-3.0-only
#pragma once
#include <charconv>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <utility>

namespace oni {
struct RemoteCommand {
    std::string id, instance, action, preset, actor, role;
    std::int64_t issued_ms = 0, expires_ms = 0, expected_session = 0;
};
inline bool bridgeId(std::string_view s) {
    if (s.size() != 32) return false;
    for (char c : s) if (!((c >= 'a' && c <= 'f') || (c >= '0' && c <= '9'))) return false;
    return true;
}
inline bool bridgeActor(std::string_view s) {
    if (s.empty() || s.size() > 80) return false;
    for (char c : s) if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
        (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.' || c == '@')) return false;
    return true;
}
inline bool bridgeAction(std::string_view s) {
    return s == "health" || s == "scan" || s == "record" || s == "stop" || s == "cancel" ||
        s == "background-on" || s == "background-off" || s == "incidents-on" ||
        s == "incidents-off" || s == "automatic-on" || s == "automatic-off";
}
// Deliberately tiny, strict line protocol. Not a general TOML or shell interpreter.
// Every field occurs once, unquoted tokens are ASCII, integer overflow is rejected.
inline std::optional<RemoteCommand> parseRemote(std::string_view input, std::string &error) {
    auto fail = [&](const char *why) -> std::optional<RemoteCommand> { error = why; return std::nullopt; };
    if (input.empty() || input.size() > 4096) return fail("Command size is invalid");
    std::map<std::string, std::string> fields;
    while (!input.empty()) {
        auto end = input.find('\n');
        auto line = input.substr(0, end);
        if (end == std::string_view::npos) input = {}; else input.remove_prefix(end + 1);
        if (!line.empty() && line.back() == '\r') line.remove_suffix(1);
        if (line.empty()) continue;
        auto split = line.find('=');
        if (split == std::string_view::npos || split == 0) return fail("Malformed command field");
        std::string key(line.substr(0, split)), value(line.substr(split + 1));
        if (key.size() > 32 || value.size() > 100 || !fields.emplace(key,value).second)
            return fail("Duplicate or oversized command field");
    }
    const char *keys[] = {"protocol", "id", "instance", "action", "preset", "actor", "role", "issued_ms", "expires_ms", "expected_session"};
    if (fields.size() != 10) return fail("Wrong number of command fields");
    for (const char *k : keys) if (!fields.contains(k)) return fail("Missing command field");
    if (fields["protocol"] != "1") return fail("Unsupported command protocol");
    RemoteCommand c;
    c.id = fields["id"]; c.instance = fields["instance"]; c.action = fields["action"];
    c.preset = fields["preset"]; c.actor = fields["actor"]; c.role = fields["role"];
    if (!bridgeId(c.id) || !bridgeId(c.instance) || !bridgeActor(c.actor) || !bridgeAction(c.action))
        return fail("Invalid command identity or action");
    if (c.role != "operator" && c.role != "manager") return fail("Invalid controller role");
    if (c.preset != "-" && c.preset != "quick" && c.preset != "lag" && c.preset != "spikes" && c.preset != "memory")
        return fail("Invalid recording preset");
    if ((c.action == "record") != (c.preset != "-")) return fail("Preset does not match the action");
    auto read = [&](const char *key, std::int64_t &value) {
        const auto &s=fields[key]; const auto result=std::from_chars(s.data(),s.data()+s.size(),value);
        return result.ec==std::errc{} && result.ptr==s.data()+s.size() && value>=0;
    };
    if (!read("issued_ms",c.issued_ms) || !read("expires_ms",c.expires_ms) || !read("expected_session",c.expected_session))
        return fail("Invalid command time or session");
    if (c.expires_ms <= c.issued_ms || c.expires_ms - c.issued_ms > 180000)
        return fail("Command lifetime must be at most three minutes");
    return c;
}
inline std::string remoteRejection(const RemoteCommand &c, std::string_view instance,
                                   std::int64_t now, bool enabled, bool management) {
    if (!enabled) return "Remote controls are disabled in oniprofiler.toml";
    if (c.instance != instance) return "Server instance changed; submit a new request";
    if (c.expires_ms <= now || c.issued_ms > now + 30000) return "Request expired or clocks differ by more than 30 seconds";
    const bool manages = c.action.find('-') != std::string::npos || c.preset == "memory";
    if (manages && (c.role != "manager" || !management)) return "Remote management is not permitted by the local policy";
    return {};
}
}
