// SPDX-License-Identifier: GPL-3.0-only
#include "oni/control_center.h"
#include <algorithm>
#include <chrono>
#include <random>
#include <endstone/form/action_form.h>
#include "core/command/arguments.h"
#include "core/stats/system_stats.h"

namespace oni {
namespace {
std::int64_t unixMs() { return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count(); }
std::int64_t steadyMs() { return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
std::string yes(bool value) { return value ? "ON" : "OFF"; }
}
ControlCenter::ControlCenter(endstone::Plugin &plugin, spark::SparkApplication &app,
        spark::endstone_adapter::EndstoneMetadataProvider &metadata, Options options)
    : plugin_(plugin), app_(app), metadata_(metadata), options_(options),
      writer_(plugin.getDataFolder() / "reports", options.retained_summaries)
{
    std::random_device random;
    static constexpr char digits[] = "0123456789abcdef";
    for (int i=0;i<32;++i) instance_id_ += digits[random() & 15];
    if (options_.remote_controls_enabled)
        bridge_ = std::make_unique<CommandBridge>(plugin_.getDataFolder()/"bridge");
    app_.profilerService().oniSetBackgroundEnabled(options_.background_enabled);
    detector_.threshold_ms = options_.incident_threshold_ms;
    detector_.sustain_ms = options_.incident_sustain_seconds * 1000LL;
    detector_.cooldown_ms = options_.incident_cooldown_seconds * 1000LL;
}
ControlCenter::~ControlCenter() { shutdown(); }
void ControlCenter::shutdown()
{
    if (stopped_) return;
    stopped_ = true; lifetime_.reset();
    for (auto *player : plugin_.getServer().getOnlinePlayers()) {
        if (player && open_forms_.contains(player->getName())) player->closeForm();
    }
    open_forms_.clear(); if (bridge_) bridge_->stop(); writer_.stop();
    const auto error = writer_.takeError();
    if (!error.empty()) plugin_.getLogger().error("OniProfiler final report write failed: {}", error);
}
bool ControlCenter::require(endstone::CommandSender &sender, const std::string &permission) const
{
    if (sender.hasPermission(permission)) return true;
    sender.sendErrorMessage("You do not have permission: " + permission); return false;
}
void ControlCenter::form(endstone::Player &player, const std::string &title, const std::string &text,
                         std::vector<Action> actions)
{
    if (!require(player, "oniprofiler.view") || stopped_) return;
    endstone::ActionForm f;
    f.setTitle("OniProfiler | " + title);
    f.setContent(text + "\n\npowered by spark");
    for (const auto &action : actions) f.addButton(action.first);
    const std::weak_ptr<int> lifetime = lifetime_;
    f.setOnSubmit([this, lifetime, actions = std::move(actions)](endstone::Player *p, int selected) {
        if (lifetime.expired() || !p) return;
        open_forms_.erase(p->getName());
        if (selected < 0 || static_cast<std::size_t>(selected) >= actions.size()) return;
        if (!require(*p, "oniprofiler.view")) return;
        try { actions[static_cast<std::size_t>(selected)].second(*p); }
        catch (const std::exception &e) { plugin_.getLogger().error("OniProfiler menu action failed: {}", e.what()); p->sendErrorMessage("That action failed. Check the server log; no success was recorded."); }
    });
    f.setOnClose([this, lifetime](endstone::Player *p) {
        if (!lifetime.expired() && p) open_forms_.erase(p->getName());
    });
    open_forms_.insert(player.getName());
    player.sendForm(f);
}
std::string ControlCenter::statusText() const
{
    const auto s = app_.profilerService().oniStatus();
    if (s.exporting) return "Recording stopped. Finalizing the native profile.";
    if (!s.running) return options_.background_enabled ? "Background monitoring is waiting, paused, or retrying. Check server logs if it stays inactive." : "Background monitoring is OFF. Statistics are still collected.";
    std::string text = s.background ? "Background monitoring is active." : "Detailed recording is active.\nStarted by: " + s.owner;
    text += "\nElapsed: " + std::to_string(std::max<std::int64_t>(0, unixMs() - s.started_ms) / 1000) + " seconds";
    if (s.ends_ms > 0) text += "\nRemaining: " + std::to_string(std::max<std::int64_t>(0, s.ends_ms - unixMs()) / 1000) + " seconds";
    text += "\nSamples: " + std::to_string(s.samples) + " | Dropped: " + std::to_string(s.dropped);
    return text;
}
std::string ControlCenter::healthText() const
{
    std::string text = explain(health_).front().title + "\n\nTPS: " + fixed(health_.tps)
        + "\nMean tick: " + fixed(health_.mspt_mean) + " ms\n95th percentile: " + fixed(health_.mspt_p95)
        + " ms\nLongest tick: " + fixed(health_.mspt_max) + " ms\nPlayers: " + std::to_string(health_.players)
        + "\nTick window: " + std::to_string(health_.mspt_span_ms / 1000) + " seconds, " + std::to_string(health_.tick_samples) + " samples";
    if (health_.cpu_percent) text += "\nProcess CPU: " + fixed(health_.cpu_percent) + "% of total host capacity";
    if (health_.rss_bytes) text += "\nResident memory: " + fixed(*health_.rss_bytes / 1048576.0) + " MiB";
    if (health_.entities && health_.chunks) text += "\nLoaded entities / chunks: " + std::to_string(*health_.entities) + " / " + std::to_string(*health_.chunks);
    text += "\nSnapshot age: " + std::to_string(std::max<std::int64_t>(0, unixMs() - health_.timestamp_ms) / 1000) + " seconds";
    return text;
}
void ControlCenter::menu(endstone::Player &player)
{
    form(player, "Control center", healthText() + "\n\n" + statusText(), {
        {"Check server health", [this](auto &p) { healthMenu(p); }},
        {"Record a performance problem", [this](auto &p) { recordMenu(p); }},
        {"Recording status and controls", [this](auto &p) { statusMenu(p); }},
        {"Inspect busy loaded areas", [this](auto &p) { areasMenu(p); }},
        {"Compare with a baseline", [this](auto &p) { comparisonMenu(p); }},
        {"Filter loaded areas by dimension", [this](auto &p) { filteredAreasMenu(p); }},
        {"Previous native reports", [this](auto &p) { reportsMenu(p); }},
        {"Monitoring and settings", [this](auto &p) { settingsMenu(p); }},
        {"Private report viewer instructions", [this](auto &p) {
            form(p, "Report viewer", "Use the private live dashboard through the separately installed OniProfiler control service and outbound agent. Ask your server owner for its address.\n\nAn offline viewer is also included: open OniProfiler-Report-Viewer.html and import reports/*.json. Native .sparkprofile files retain Spark viewer compatibility.", {{"Back", [this](auto &q){ menu(q); }}});
        }}
    });
}
void ControlCenter::healthMenu(endstone::Player &player)
{
    std::string body = healthText();
    for (const auto &f : explain(health_)) body += "\n\n" + f.title + "\n" + f.detail;
    form(player, "Health", body, {
        {"Refresh screen (cached measurements)", [this](auto &p){ healthMenu(p); }},
        {"Save private health summary", [this](auto &p){ saveHealth(p, "Manual health check"); }},
        {"Detailed Spark health in chat", [this](auto &p){ spark::endstone_adapter::EndstoneCommandSender sender(p); app_.dispatchCommand(sender, {"health"}); }},
        {"Back", [this](auto &p){ menu(p); }}
    });
}
void ControlCenter::recordMenu(endstone::Player &player)
{
    if (!require(player, "oniprofiler.record")) return;
    std::vector<Action> actions;
    for (const auto &preset : presets()) actions.emplace_back(preset.title + " | " + std::to_string(preset.seconds) + "s", [this, preset](auto &p){ confirmPreset(p, preset); });
    actions.emplace_back("Back", [this](auto &p){ menu(p); });
    form(player, "Choose an investigation", "All presets save the native profile locally.\nA detailed recording temporarily replaces the background sampler.\nOnly one native session can run at a time.", std::move(actions));
}
void ControlCenter::confirmPreset(endstone::Player &player, Preset preset)
{
    if (!require(player, "oniprofiler.record")) return;
    std::string body = preset.title + "\nDuration: " + std::to_string(preset.seconds) + " seconds\nStorage: local only\nBackground monitoring resumes when enabled.";
    if (preset.only_over_ms) body += "\nOnly ticks over " + std::to_string(preset.only_over_ms) + " ms are retained.";
    if (preset.allocation) body += "\n\nAdvanced: native allocation profiling can add overhead. It is not a Python/JavaScript heap inspector and cannot prove a leak from one recording.";
    form(player, "Start recording?", body, {
        {"Start and save locally", [this, preset](auto &p){ if (start(p, preset)) statusMenu(p); }},
        {"Go back", [this](auto &p){ recordMenu(p); }}
    });
}
bool ControlCenter::start(endstone::CommandSender &sender, const Preset &preset, bool automatic)
{
    observeSession(); // Deliver the previous export receipt before starting another recording.
    if (!automatic && !require(sender, "oniprofiler.record")) return false;
    if (!automatic && preset.allocation && !require(sender, "oniprofiler.advanced")) return false;
    const auto before = app_.profilerService().oniStatus();
    if (before.exporting || (before.running && !before.background)) {
        sender.sendErrorMessage("Another recording is active or finalizing. Use the status screen."); return false;
    }
    const auto id = newId();
    spark::endstone_adapter::EndstoneCommandSender adapter(sender);
    app_.profilerService().cmdStart(adapter, spark::Arguments(presetTokens(preset, "OniProfiler " + id + " " + preset.title)));
    const auto after = app_.profilerService().oniStatus();
    if (!after.running || after.background || after.started_ms == 0) return false;
    run_ = Run{id, (automatic ? "Automatic incident: " : "") + preset.title, preset.key, after.owner,
               after.started_ms, health_, {}, 0, 0, false, after.allocation, after.interval, after.threshold};
    sender.sendMessage("OniProfiler recording started. Results will stay in the plugin's data folder.");
    return true;
}
void ControlCenter::statusMenu(endstone::Player &player)
{
    const auto status = app_.profilerService().oniStatus();
    std::vector<Action> actions;
    if (status.running) {
        actions.emplace_back("Stop and save locally", [this, id=status.started_ms](auto &p){ stop(p, id, false); });
        actions.emplace_back("Discard recording...", [this, id=status.started_ms](auto &p){
            form(p, "Discard this recording?", "This discards native samples without producing a profile. It does not delete older reports.", {
                {"Discard this recording", [this, id](auto &q){ stop(q, id, true); }},
                {"Keep recording", [this](auto &q){ statusMenu(q); }}
            });
        });
        actions.emplace_back("Share a live viewer...", [this](auto &p){ shareMenu(p); });
    }
    actions.emplace_back("Refresh status", [this](auto &p){ statusMenu(p); });
    actions.emplace_back("Back", [this](auto &p){ menu(p); });
    form(player, "Recording", statusText(), std::move(actions));
}
void ControlCenter::stop(endstone::CommandSender &sender, std::int64_t expected, bool discard)
{
    const auto s = app_.profilerService().oniStatus();
    if (!s.running || !mayControl(sender.getName(), s.owner, sender.hasPermission("oniprofiler.record"),
                                  sender.hasPermission("oniprofiler.manage"), expected, s.started_ms)) {
        sender.sendErrorMessage("The recording changed, or you are not its owner. Managers can control other recordings."); return;
    }
    if (s.background && !require(sender, "oniprofiler.manage")) return;
    spark::endstone_adapter::EndstoneCommandSender adapter(sender);
    if (discard) {
        app_.profilerService().cmdCancel(adapter);
        if (!app_.profilerService().running()) run_.reset();
    } else app_.profilerService().cmdStop(adapter, spark::Arguments({"stop", "--save-to-file"}));
}
void ControlCenter::areasMenu(endstone::Player &player, std::size_t page)
{
    if (!require(player, "oniprofiler.locations")) return;
    const auto pages = std::max<std::size_t>(1, (areas_.size() + 5) / 6);
    page = std::min(page, pages - 1);
    std::string body = "Loaded chunks only. Entity count is not measured tick cost.\n";
    body += areas_ms_ ? "Snapshot age: " + std::to_string(std::max<std::int64_t>(0, unixMs()-areas_ms_)/1000) + " seconds" : "No detailed snapshot has been requested.";
    body += "\nPage " + std::to_string(page+1) + " / " + std::to_string(pages);
    std::vector<Action> actions;
    for (std::size_t i=page*6; i<std::min(areas_.size(), page*6+6); ++i) {
        const Area a = areas_[i];
        actions.emplace_back(a.dimension + " | " + std::to_string(a.entities) + " entities | " + std::to_string(a.chunk_x) + ", " + std::to_string(a.chunk_z),
            [this, a, page](auto &p){
                if (!require(p, "oniprofiler.locations")) return;
                const auto bx = static_cast<std::int64_t>(a.chunk_x)*16;
                const auto bz = static_cast<std::int64_t>(a.chunk_z)*16;
                std::string body = "Dimension: " + a.dimension + "\nBlock X: " + std::to_string(bx) + " to " + std::to_string(bx+15)
                    + "\nBlock Z: " + std::to_string(bz) + " to " + std::to_string(bz+15) + "\n\nEntity types:";
                for (const auto &[type, count] : a.types) body += "\n" + type + ": " + std::to_string(count);
                body += "\n\nThis snapshot does not measure individual entity cost. No teleport or world changes are performed.";
                form(p, "Loaded area", body, {{"Back", [this, page](auto &q){ areasMenu(q, page); }}});
            });
    }
    if (page) actions.emplace_back("Previous page", [this,page](auto &p){ areasMenu(p,page-1); });
    if (page+1<pages) actions.emplace_back("Next page", [this,page](auto &p){ areasMenu(p,page+1); });
    actions.emplace_back("Request a new snapshot...", [this](auto &p){
        form(p,"Refresh loaded areas?", "This reads currently loaded chunks and actors on the server thread. Large loaded worlds may experience a brief tick-time cost.\n\nIt never intentionally loads new chunks. Refreshes share a server-wide cooldown.", {
            {"Scan loaded areas", [this](auto &q){ refreshAreas(q); areasMenu(q); }},
            {"Use cached snapshot", [this](auto &q){ areasMenu(q); }}
        });
    });
    actions.emplace_back("Back", [this](auto &p){ menu(p); });
    form(player, "Busy areas", body, std::move(actions));
}
void ControlCenter::refreshAreas(endstone::CommandSender &sender)
{
    if (!require(sender, "oniprofiler.locations")) return;
    const auto now = steadyMs();
    if (area_scan_steady_ms_ >= 0 && now-area_scan_steady_ms_ < options_.area_cooldown_seconds*1000LL) {
        sender.sendMessage("The loaded-area snapshot is on cooldown. Use the cached snapshot."); return;
    }
    area_scan_steady_ms_ = now;
    spark::ExportContext context;
    metadata_.gatherWorldMetadata(context);
    if (!context.world.present) { sender.sendErrorMessage("World metadata was unavailable. The previous snapshot was retained."); return; }
    std::vector<Area> result;
    for (const auto &world : context.world.worlds)
        for (const auto &region : world.regions)
            for (const auto &chunk : region.chunks)
                result.push_back(Area{world.name,chunk.x,chunk.z,chunk.total_entities,chunk.entity_counts});
    rankAreas(result, static_cast<std::size_t>(options_.max_areas));
    areas_ = std::move(result); areas_ms_ = unixMs();
    writer_.dashboard(document("dashboard"));
    sender.sendMessage("Loaded-area snapshot refreshed. Ranked by entity count, not lag cost.");
}
void ControlCenter::reportsMenu(endstone::Player &player, std::size_t page)
{
    if (!require(player, "oniprofiler.reports")) return;
    auto entries = app_.activityLog().entries();
    std::stable_sort(entries.begin(), entries.end(), [](const auto &a, const auto &b){ return a.time_ms>b.time_ms; });
    const auto pages = std::max<std::size_t>(1,(entries.size()+5)/6);
    page = std::min(page,pages-1);
    std::vector<Action> actions;
    for (std::size_t i=page*6; i<std::min(entries.size(),page*6+6); ++i) {
        const auto entry=entries[i];
        actions.emplace_back(entry.type + " | " + entry.user_name + " | " + (entry.data_type==spark::Activity::DataType::File ? "Local file" : "Shared URL"),
            [this,entry,page](auto &p){
                if (!require(p,"oniprofiler.reports")) return;
                form(p,"Native report", "Type: " + entry.type + "\nTriggered by: " + entry.user_name
                    + "\nUnix time (ms): " + std::to_string(entry.time_ms) + "\n\n" + entry.data_value
                    + "\n\nA history entry does not guarantee the file or remote link still exists. Local summary JSON files are in reports/.",
                    {{"Print location in chat", [this,entry](auto &q){ if (require(q,"oniprofiler.reports")) q.sendMessage(entry.data_value); }},
                     {"Back",[this,page](auto &q){ reportsMenu(q,page); }}});
            });
    }
    if (page) actions.emplace_back("Previous page", [this,page](auto &p){ reportsMenu(p,page-1); });
    if (page+1<pages) actions.emplace_back("Next page", [this,page](auto &p){ reportsMenu(p,page+1); });
    actions.emplace_back("Back",[this](auto &p){ menu(p); });
    form(player,"Native report history", "Page " + std::to_string(page+1) + " / " + std::to_string(pages)
         + "\nSpark's activity history persists across restarts. No older Spark data folder is modified or imported automatically.",std::move(actions));
}
void ControlCenter::settingsMenu(endstone::Player &player)
{
    if (!require(player,"oniprofiler.manage")) return;
    form(player,"Monitoring", "Background sampler: " + yes(options_.background_enabled)
        + "\nIncident alerts: " + yes(options_.incidents_enabled) + "\nAutomatic detailed recordings: " + yes(options_.automatic_profiles)
        + "\nExternal sharing permitted: " + yes(options_.allow_external_sharing)
        + "\n\nAn incident needs consecutive ticks of at least " + std::to_string(options_.incident_threshold_ms)
        + " ms for " + std::to_string(options_.incident_sustain_seconds) + " seconds. Cooldown: " + std::to_string(options_.incident_cooldown_seconds) + " seconds."
        + "\n\nAutomatic profile starts check a periodically measured storage budget. A running recording can exceed that budget. Existing native profiles are never automatically deleted.", {
        {"Toggle background monitoring",[this,value=!options_.background_enabled](auto &p){ updateOption(p,"background",value); }},
        {"Toggle incident alerts",[this,value=!options_.incidents_enabled](auto &p){ updateOption(p,"incidents",value); }},
        {"Change automatic recordings...",[this,value=!options_.automatic_profiles](auto &p){
            form(p,"Automatic detailed recordings", "Set automatic recordings to " + yes(value) + "?\n\nWhen enabled, a sustained incident may replace background sampling with a 60-second local profile. It will not interrupt an existing foreground session. There are no retroactive pre-trigger stack samples in that new recording.",
                {{"Apply",[this,value](auto &q){ updateOption(q,"automatic",value); }},{"Back",[this](auto &q){ settingsMenu(q); }}});
        }},
        {"Back",[this](auto &p){ menu(p); }}
    });
}
void ControlCenter::updateOption(endstone::Player &player,const std::string &key,bool value)
{
    if (!require(player,"oniprofiler.manage")) return;
    auto changed=options_;
    if (key=="background") changed.background_enabled=value;
    else if (key=="incidents") changed.incidents_enabled=value;
    else if (key=="automatic") changed.automatic_profiles=value;
    else return;
    std::string error;
    if (!changed.save(plugin_.getDataFolder()/"oniprofiler.toml",error)) { player.sendErrorMessage("Settings were not changed: "+error); return; }
    options_=changed;
    if (key=="background") {
        auto &service=app_.profilerService();
        service.oniSetBackgroundEnabled(value);
        if (!value && service.isBackgroundRunning()) {
            spark::endstone_adapter::EndstoneCommandSender adapter(player); service.cmdCancel(adapter);
        }
    }
    if (!options_.incidents_enabled) detector_.reset();
    settingsMenu(player);
}
void ControlCenter::shareMenu(endstone::Player &player)
{
    if (!require(player,"oniprofiler.share")) return;
    if (!options_.allow_external_sharing) {
        player.sendErrorMessage("External sharing is disabled. An owner must enable allow_external_sharing in oniprofiler.toml and restart."); return;
    }
    const auto s=app_.profilerService().oniStatus();
    form(player,"External live viewer", "Opening the live viewer sends profile data and server metadata to Spark's configured external services. Review the sharing documentation first.\n\nThe normal local workflow does not need this.", {
        {"Approve and open external viewer",[this,id=s.started_ms](auto &p){
            if (!require(p,"oniprofiler.share") || !options_.allow_external_sharing) return;
            const auto current=app_.profilerService().oniStatus();
            if (!current.running || !mayControl(p.getName(),current.owner,p.hasPermission("oniprofiler.record"),p.hasPermission("oniprofiler.manage"),id,current.started_ms)) {
                p.sendErrorMessage("The session changed, or you do not control it."); return;
            }
            spark::endstone_adapter::EndstoneCommandSender adapter(p); app_.profilerService().cmdOpen(adapter);
        }},
        {"Keep it private",[this](auto &p){ statusMenu(p); }}
    });
}
void ControlCenter::refreshHealth()
{
    const auto stats=app_.statistics().snapshot();
    const auto &t=stats.tps.last_10s;
    const auto &m=stats.mspt.last_10s;
    const auto &c=stats.cpu.process_last_10s;
    Health h;
    h.timestamp_ms=stats.generated_time_ms; h.history_ms=stats.history_span_ms;
    h.tps_span_ms=t.span_ms; h.mspt_span_ms=m.span_ms; h.cpu_span_ms=c.span_ms; h.tick_samples=m.samples;
    if (t.present) h.tps=t.value;
    if (m.present) { h.mspt_mean=m.mean; h.mspt_p95=m.percentile95; h.mspt_max=m.max; }
    if (c.present) h.cpu_percent=c.value*100.0;
    h.players=metadata_.playerCount();
    const auto gauges=metadata_.worldGauges();
    if (gauges.first>=0) h.entities=gauges.first;
    if (gauges.second>=0) h.chunks=gauges.second;
    const auto process=spark::gatherProcessStats();
    if (process.rss_present) h.rss_bytes=static_cast<double>(process.rss_bytes);
    health_=h;
    history_.push_back(h);
    while (history_.size()>180) history_.pop_front();
}
std::string ControlCenter::newId() { return std::to_string(unixMs()) + '-' + std::to_string(++report_counter_); }
std::string ControlCenter::document(const std::string &kind,const Run *run,const std::string &result,const std::string &outcome) const
{
    const auto session=app_.profilerService().oniStatus();
    const Health &display=run?run->after:health_;
    std::string json="{\"schema_version\":1,\"product\":\"OniProfiler powered by spark\",\"version\":"+quote(version)
        +",\"instance_id\":"+quote(instance_id_)+",\"capabilities\":{\"remote_controls\":"+(options_.remote_controls_enabled?"true":"false")+",\"remote_management\":"+(options_.remote_management_enabled?"true":"false")+"},\"upstream_commit\":"+quote(upstream_commit)+",\"kind\":"+quote(kind)+",\"generated_ms\":"+std::to_string(unixMs())
        +",\"health\":"+healthJson(display)+",\"findings\":"+findingsJson(display)+",\"loaded_areas\":"+areasJson(areas_,areas_ms_)
        +",\"session\":{\"running\":"+(session.running?"true":"false")+",\"background\":"+(session.background?"true":"false")
        +",\"exporting\":"+(session.exporting?"true":"false")+",\"started_ms\":"+std::to_string(session.started_ms)+",\"ends_ms\":"+std::to_string(session.ends_ms)+",\"owner\":"+quote(session.started_ms==remote_session_?remote_owner_:session.owner)+",\"samples\":"+std::to_string(session.samples)+",\"description\":"+quote(statusText())+"},\"history\":[";
    bool first=true;
    for (const auto &h:history_) {
        if (run && (h.timestamp_ms<run->started_ms || h.timestamp_ms>run->after.timestamp_ms)) continue;
        if (!first) json+=',';
        first=false; json+=healthJson(h);
    }
    json+="],\"recording\":";
    if (run) {
        json+="{\"id\":"+quote(run->id)+",\"title\":"+quote(run->title)+",\"preset\":"+quote(run->preset)+",\"owner\":"+quote(run->owner)
            +",\"started_ms\":"+std::to_string(run->started_ms)+",\"mode\":"+quote(run->allocation?"allocation":"execution")
            +",\"interval\":"+std::to_string(run->interval)+",\"only_ticks_over_ms\":"+std::to_string(run->threshold)
            +",\"samples\":"+std::to_string(run->samples)+",\"dropped_samples\":"+std::to_string(run->dropped)
            +",\"before\":"+healthJson(run->before)+",\"after\":"+healthJson(run->after)
            +",\"native_outcome\":"+quote(outcome)+",\"native_result\":"+quote(result)+"}";
    } else json+="null";
    json+=",\"native_reports\":["; first=true;
    for (const auto &entry:app_.activityLog().entries()) {
        if (!first) json+=','; first=false;
        json+="{\"owner\":"+quote(entry.user_name)+",\"time_ms\":"+std::to_string(entry.time_ms)+",\"type\":"+quote(entry.type)
            +",\"storage\":"+quote(entry.data_type==spark::Activity::DataType::File?"file":"url")+",\"result\":"+quote(entry.data_value)+"}";
    }
    json+="],\"limitations\":[\"Aggregate statistics do not identify a specific lag cause.\",\"Loaded-area rankings count entities; they do not measure per-chunk CPU cost.\",\"The before/after fields are rolling 10-second snapshots, not full-session averages.\",\"Unavailable measurements are null, never invented zeroes.\",\"Native profiles can contain sensitive server metadata; review before sharing.\",\"Remote control requires the separate authenticated control service, an outbound agent, and explicit local permission.\"]}";
    return json;
}
bool ControlCenter::saveHealth(endstone::CommandSender &sender,const std::string &reason)
{
    if (!require(sender,"oniprofiler.reports")) return false;
    const auto id=newId();
    std::string json=document("health");
    json.pop_back(); json+=",\"title\":"+quote(reason)+"}";
    if (!writer_.report(id,std::move(json))) { sender.sendErrorMessage("The report queue is full or stopped. No summary was queued."); return false; }
    sender.sendMessage("Health summary queued for reports/report-"+id+".json. Disk failures are reported in the server log.");
    return true;
}
void ControlCenter::observeSession()
{
    const auto s=app_.profilerService().oniStatus();
    if (s.running && !s.background && (!run_ || run_->started_ms!=s.started_ms)) {
        run_=Run{newId(),"Advanced native recording","advanced",s.owner,s.started_ms,health_,{},0,0,false,s.allocation,s.interval,s.threshold};
    }
    if (!run_) return;
    if (s.running && !s.background && s.started_ms==run_->started_ms) { run_->samples=s.samples; run_->dropped=s.dropped; return; }
    if (!run_->ended) { refreshHealth(); run_->after=health_; run_->ended=true; }
    if (s.exporting) return;
    const auto receipt=app_.profilerService().oniLastExport();
    if (receipt.started_ms==run_->started_ms) {
        run_->samples=receipt.samples; run_->dropped=receipt.dropped;
        const auto outcome=receipt.outcome==spark::ExportOutcome::Saved?"saved":receipt.outcome==spark::ExportOutcome::Uploaded?"uploaded":"failed";
        if (!writer_.report(run_->id,document("recording",&*run_,receipt.result,outcome)))
            plugin_.getLogger().error("OniProfiler summary queue is full; native export result is still available in Spark's log.");
    }
    run_.reset();
}
void ControlCenter::incident()
{
    plugin_.getLogger().warning("OniProfiler: sustained slow ticks detected ({} ms for {} s).",options_.incident_threshold_ms,options_.incident_sustain_seconds);
    for (auto *p:plugin_.getServer().getOnlinePlayers()) {
        if (p && p->hasPermission("oniprofiler.alerts")) p->sendMessage("OniProfiler: sustained slow ticks detected. Open /oniprofiler health to investigate.");
    }
    const auto id=newId();
    std::string json=document("incident");
    json.pop_back(); json+=",\"trigger\":{\"threshold_ms\":"+std::to_string(options_.incident_threshold_ms)
        +",\"sustain_seconds\":"+std::to_string(options_.incident_sustain_seconds)+",\"detail\":\"Consecutive slow tick observations. This is not a cause diagnosis.\"}}";
    if (!writer_.report(id,std::move(json))) plugin_.getLogger().warning("Incident summary was not queued: writer queue is full.");
    if (options_.automatic_profiles && writer_.diskMeasured()
        && writer_.profileBytes()<static_cast<std::uint64_t>(options_.automatic_storage_limit_mb)*1048576ULL) {
        const auto s=app_.profilerService().oniStatus();
        if (!s.exporting && (!s.running || s.background)) start(plugin_.getServer().getCommandSender(),presets()[1],true);
    }
}
void ControlCenter::tick(double mspt)
{
    if (stopped_) return;
    const auto now=steadyMs();
    if (now>=next_refresh_) {
        refreshHealth(); next_refresh_=now+options_.refresh_seconds*1000LL;
        writer_.dashboard(document("dashboard"));
        const auto error=writer_.takeError();
        if (!error.empty()) plugin_.getLogger().error("OniProfiler report write failed: {}",error);
    }
    observeSession();
    if (bridge_) processRemote();
    if (options_.incidents_enabled && detector_.observe(mspt,now)) incident();
}
bool ControlCenter::command(endstone::CommandSender &sender,const std::vector<std::string> &tokens)
{
    if (!require(sender,"oniprofiler.view")) return true;
    const std::string action=tokens.empty()?"menu":tokens.front();
    auto *player=sender.asPlayer();
    if (action=="menu" && player) menu(*player);
    else if (action=="health") { if (player) healthMenu(*player); else sender.sendMessage(healthText()); }
    else if (action=="status") { if (player) statusMenu(*player); else sender.sendMessage(statusText()); }
    else if (action=="record") {
        if (tokens.size()==1 && player) recordMenu(*player);
        else {
            const std::string selected=tokens.size()>1?tokens[1]:"lag";
            const auto found=std::find_if(presets().begin(),presets().end(),[&](const auto &p){ return p.key==selected; });
            if (found==presets().end()) sender.sendErrorMessage("Choose quick, lag, spikes, or memory.");
            else if (player) confirmPreset(*player,*found); else start(sender,*found);
        }
    }
    else if (action=="stop") stop(sender,app_.profilerService().oniStatus().started_ms,false);
    else if (action=="cancel") {
        if (player) statusMenu(*player);
        else if (tokens.size()>1 && tokens[1]=="confirm") stop(sender,app_.profilerService().oniStatus().started_ms,true);
        else sender.sendMessage("Use oniprofiler cancel confirm to discard the active recording.");
    }
    else if (action=="areas") { if (player) areasMenu(*player); else sender.sendMessage("Use oniprofiler scan to request a loaded-area snapshot; it can briefly cost tick time."); }
    else if (action=="scan") { if (player) areasMenu(*player); else refreshAreas(sender); }
    else if (action=="reports" && player) reportsMenu(*player);
    else if (action=="compare" && player) comparisonMenu(*player);
    else if (action=="settings" && player) settingsMenu(*player);
    else if (action=="export") saveHealth(sender,"Manual health check");
    else if (action=="share" && player) shareMenu(*player);
    else sender.sendMessage("OniProfiler powered by spark\n/oniprofiler [menu|health|status|record quick/lag/spikes/memory|stop|cancel|areas|scan|reports|compare|settings|export|share]\nConsole: omit /. Console cancel requires confirm. /spark retains advanced native commands.");
    return true;
}
bool ControlCenter::advanced(endstone::CommandSender &sender,std::vector<std::string> tokens)
{
    if (tokens.empty() && sender.asPlayer()) return command(sender,{});
    if (!require(sender,"oniprofiler.advanced")) return true;
    const auto policy = classifyAdvanced(tokens);
    if (policy.external && (!options_.allow_external_sharing || !require(sender,"oniprofiler.share"))) {
        sender.sendErrorMessage("External sharing is disabled or unauthorized. Use the private local workflow."); return true;
    }
    if (policy.starts && !require(sender,"oniprofiler.record")) return true;
    if (policy.mutates) {
        const auto s=app_.profilerService().oniStatus();
        if (s.running && (s.background ? !sender.hasPermission("oniprofiler.manage") :
            !mayControl(sender.getName(),s.owner,sender.hasPermission("oniprofiler.record"),sender.hasPermission("oniprofiler.manage"),s.started_ms,s.started_ms))) {
            sender.sendErrorMessage("Only the recording owner or a manager may change this session. Background recordings require management permission."); return true;
        }
    }
    // Includes the upstream --stop and --upload aliases, not only action words.
    if (policy.force_local) tokens.push_back("--save-to-file");
    spark::endstone_adapter::EndstoneCommandSender adapter(sender);
    app_.dispatchCommand(adapter,tokens);
    return true;
}
void ControlCenter::comparisonMenu(endstone::Player &player)
{
    if (!require(player,"oniprofiler.reports")) return;
    std::string text="Save a baseline, make one controlled change, and return here under a similar workload. This compares rolling snapshots, not two complete native profiles.";
    if (comparison_baseline_) {
        const auto &b=*comparison_baseline_;
        text+="\n\nBaseline age: "+std::to_string(std::max<std::int64_t>(0,unixMs()-b.timestamp_ms)/1000)+" seconds"
            +"\nMean tick: "+fixed(b.mspt_mean)+" -> "+fixed(health_.mspt_mean)+" ms"
            +"\n95th percentile: "+fixed(b.mspt_p95)+" -> "+fixed(health_.mspt_p95)+" ms"
            +"\nTPS: "+fixed(b.tps)+" -> "+fixed(health_.tps)
            +"\nPlayers: "+std::to_string(b.players)+" -> "+std::to_string(health_.players);
        if(b.players!=health_.players)text+="\nCAUTION: player counts differ. Workloads may not be comparable.";
        if(b.tick_samples<20||health_.tick_samples<20)text+="\nCAUTION: too few tick samples for a useful comparison.";
    }
    form(player,"Before and after",text,{
        {"Use current health as baseline",[this](auto &p){if(require(p,"oniprofiler.reports")){comparison_baseline_=health_;comparisonMenu(p);}}},
        {"Save current snapshot to report library",[this](auto &p){saveHealth(p,"Comparison snapshot");}},
        {"Refresh comparison",[this](auto &p){comparisonMenu(p);}},
        {"Back",[this](auto &p){menu(p);}}
    });
}
void ControlCenter::filteredAreasMenu(endstone::Player &player,const std::string &dimension,std::size_t page)
{
    if (!require(player,"oniprofiler.locations")) return;
    std::vector<Action> actions;
    if(dimension.empty()){
        std::set<std::string> dimensions;
        for(const auto &a:areas_)dimensions.insert(a.dimension);
        for(const auto &name:dimensions)actions.emplace_back(name,[this,name](auto &p){filteredAreasMenu(p,name);});
        actions.emplace_back("All areas and snapshot controls",[this](auto &p){areasMenu(p);});
        actions.emplace_back("Back",[this](auto &p){menu(p);});
        form(player,"Choose a dimension","Cached loaded chunks only. A large entity count is not proof of lag.",std::move(actions));return;
    }
    std::vector<Area> selected;
    for(const auto &a:areas_)if(a.dimension==dimension)selected.push_back(a);
    auto pages=std::max<std::size_t>(1,(selected.size()+7)/8);page=std::min(page,pages-1);
    std::string text=dimension+"\nPage "+std::to_string(page+1)+" / "+std::to_string(pages);
    for(std::size_t i=page*8;i<std::min(selected.size(),page*8+8);++i){
        const auto &a=selected[i];text+="\nChunk "+std::to_string(a.chunk_x)+", "+std::to_string(a.chunk_z)+": "+std::to_string(a.entities)+" entities";
    }
    if(page)actions.emplace_back("Previous",[this,dimension,page](auto &p){filteredAreasMenu(p,dimension,page-1);});
    if(page+1<pages)actions.emplace_back("Next",[this,dimension,page](auto &p){filteredAreasMenu(p,dimension,page+1);});
    actions.emplace_back("Choose dimension",[this](auto &p){filteredAreasMenu(p);});
    form(player,"Filtered loaded areas",text,std::move(actions));
}
void ControlCenter::processRemote()
{
    const auto bridge_error=bridge_->takeError();
    if(!bridge_error.empty())plugin_.getLogger().error("OniProfiler bridge: {}",bridge_error);
    auto command=bridge_->pop();if(!command)return;
    const auto &c=*command;
    auto reject=[&](const std::string &why){bridge_->acknowledge(c.id,"rejected",why);};
    const auto policy=remoteRejection(c,instance_id_,unixMs(),options_.remote_controls_enabled,options_.remote_management_enabled);
    if(!policy.empty()){reject(policy);return;}
    try{
        auto &console=plugin_.getServer().getCommandSender();
        auto &service=app_.profilerService();
        auto session=service.oniStatus();
        if(c.action=="record"){
            auto it=std::find_if(presets().begin(),presets().end(),[&](const auto &p){return p.key==c.preset;});
            if(it==presets().end()||!start(console,*it)){reject("Recording did not start. Another session may be active.");return;}
            remote_owner_=c.actor;remote_session_=service.oniStatus().started_ms;
            if(run_)run_->owner="dashboard/"+c.actor;
            bridge_->acknowledge(c.id,"applied","Recording started; results remain local unless agent synchronization is enabled",remote_session_);
        }else if(c.action=="stop"||c.action=="cancel"){
            if(!session.running||session.started_ms!=c.expected_session){reject("Session changed; refresh before trying again");return;}
            const bool own=session.started_ms==remote_session_&&c.actor==remote_owner_;
            const bool manage=c.role=="manager"&&options_.remote_management_enabled;
            if(!own&&!manage){reject("You do not own this recording, and remote management is disabled or unauthorized");return;}
            if(session.background&&!manage){reject("Background sessions require remote management");return;}
            stop(console,c.expected_session,c.action=="cancel");
            const auto after=service.oniStatus();
            if(after.running&&after.started_ms==session.started_ms){reject("Native service did not stop this session");return;}
            bridge_->acknowledge(c.id,"applied",c.action=="cancel"?"Recording discarded":"Recording stopped; export completion will appear separately",session.started_ms);
        }else if(c.action=="scan"){
            const auto before=areas_ms_;refreshAreas(console);
            if(areas_ms_==before){reject("Scan was not refreshed, usually because the shared cooldown has not elapsed");return;}
            bridge_->acknowledge(c.id,"applied","Loaded-area snapshot refreshed; counts are not per-chunk CPU measurements");
        }else if(c.action=="health"){
            refreshHealth();
            if(!saveHealth(console,"Remote health check by "+c.actor)){reject("Health summary could not be queued");return;}
            bridge_->acknowledge(c.id,"applied","Health refreshed and summary queued; report storage errors are logged separately");
        }else{
            auto changed=options_;const bool enabled=c.action.ends_with("-on");
            if(c.action.starts_with("background-"))changed.background_enabled=enabled;
            else if(c.action.starts_with("incidents-"))changed.incidents_enabled=enabled;
            else if(c.action.starts_with("automatic-"))changed.automatic_profiles=enabled;
            else{reject("Unsupported management action");return;}
            std::string error;
            if(!changed.save(plugin_.getDataFolder()/"oniprofiler.toml",error)){reject("Settings were not saved: "+error);return;}
            options_=changed;
            if(c.action.starts_with("background-")){
                service.oniSetBackgroundEnabled(enabled);
                if(!enabled&&service.isBackgroundRunning()){
                    spark::endstone_adapter::EndstoneCommandSender adapter(console);service.cmdCancel(adapter);
                }
            }
            if(!options_.incidents_enabled)detector_.reset();
            bridge_->acknowledge(c.id,"applied","Monitoring setting saved");
        }
        writer_.dashboard(document("dashboard"));
    }catch(const std::exception &e){bridge_->acknowledge(c.id,"error",std::string("Action failed; inspect server logs: ")+e.what());}
}
}
