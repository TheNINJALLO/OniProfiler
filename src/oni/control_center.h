// SPDX-License-Identifier: GPL-3.0-only
#pragma once
#include <deque>
#include <functional>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>
#include <endstone/endstone.hpp>
#include "application/spark_application.h"
#include "platform/endstone/adapters.h"
#include "oni/domain.h"
#include "oni/command_bridge.h"
#include "oni/options.h"
#include "oni/report_writer.h"

namespace oni {
class ControlCenter {
public:
    ControlCenter(endstone::Plugin &plugin, spark::SparkApplication &app,
                  spark::endstone_adapter::EndstoneMetadataProvider &metadata, Options options);
    ~ControlCenter();
    bool command(endstone::CommandSender &sender, const std::vector<std::string> &tokens);
    bool advanced(endstone::CommandSender &sender, std::vector<std::string> tokens);
    void tick(double mspt);
    void shutdown();
private:
    using Action = std::pair<std::string, std::function<void(endstone::Player &)>>;
    struct Run {
        std::string id, title, preset, owner;
        std::int64_t started_ms = 0;
        Health before, after;
        std::uint64_t samples = 0, dropped = 0;
        bool ended = false;
        bool allocation = false;
        int interval = 0;
        std::int64_t threshold = 0;
    };
    bool require(endstone::CommandSender &sender, const std::string &permission) const;
    void form(endstone::Player &player, const std::string &title, const std::string &text, std::vector<Action> actions);
    void menu(endstone::Player &player);
    void healthMenu(endstone::Player &player);
    void recordMenu(endstone::Player &player);
    void confirmPreset(endstone::Player &player, Preset preset);
    bool start(endstone::CommandSender &sender, const Preset &preset, bool automatic = false);
    void statusMenu(endstone::Player &player);
    void stop(endstone::CommandSender &sender, std::int64_t expected, bool discard);
    void areasMenu(endstone::Player &player, std::size_t page = 0);
    void refreshAreas(endstone::CommandSender &sender);
    void reportsMenu(endstone::Player &player, std::size_t page = 0);
    void settingsMenu(endstone::Player &player);
    void updateOption(endstone::Player &player, const std::string &key, bool value);
    void shareMenu(endstone::Player &player);
    void observeSession();
    void refreshHealth();
    bool saveHealth(endstone::CommandSender &sender, const std::string &reason);
    std::string healthText() const;
    std::string statusText() const;
    std::string document(const std::string &kind, const Run *run = nullptr,
                         const std::string &result = {}, const std::string &outcome = {}) const;
    void incident();
    void processRemote();
    void comparisonMenu(endstone::Player &player);
    void filteredAreasMenu(endstone::Player &player, const std::string &dimension = {}, std::size_t page = 0);
    std::string newId();
    endstone::Plugin &plugin_;
    spark::SparkApplication &app_;
    spark::endstone_adapter::EndstoneMetadataProvider &metadata_;
    Options options_;
    ReportWriter writer_;
    std::unique_ptr<CommandBridge> bridge_;
    std::string instance_id_;
    std::string remote_owner_;
    std::int64_t remote_session_ = 0;
    std::optional<Health> comparison_baseline_;
    IncidentDetector detector_;
    Health health_;
    std::deque<Health> history_;
    std::vector<Area> areas_;
    std::int64_t areas_ms_ = 0, area_scan_steady_ms_ = -1, next_refresh_ = 0;
    std::uint64_t report_counter_ = 0;
    std::optional<Run> run_;
    std::shared_ptr<int> lifetime_ = std::make_shared<int>(0);
    std::set<std::string> open_forms_;
    bool stopped_ = false;
};
}
