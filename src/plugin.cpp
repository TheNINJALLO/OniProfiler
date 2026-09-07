// SPDX-License-Identifier: GPL-3.0-only
// Bootstrap derived from EndstoneMC/spark src/plugin.cpp at 8958173.
// Upstream author: ReallocAll. OniProfiler additions: TheN1NJ4LL0 project, 2026.
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include <endstone/endstone.hpp>
#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#include <sys/syscall.h>
#endif
#include "application/spark_application.h"
#include "core/command/arguments.h"
#include "core/config/spark_config.h"
#include "core/config/trusted_viewers.h"
#include "core/stats/executable_hash.h"
#include "net/profile_file.h"
#include "platform/endstone/adapters.h"
#include "platform/endstone/papi_integration.h"
#include "spark_constants.h"
#include "oni/control_center.h"
#include "oni/domain.h"
#include "oni/options.h"
namespace {
std::uint64_t threadId()
{
#ifdef _WIN32
    return static_cast<std::uint64_t>(::GetCurrentThreadId());
#else
    return static_cast<std::uint64_t>(::syscall(SYS_gettid));
#endif
}
}
class OniProfilerPlugin : public endstone::Plugin {
public:
    void onLoad() override
    {
        getLogger().info("OniProfiler {} native plugin loaded; waiting for post-world enable.", oni::version);
    }
    void onEnable() override
    {
        // Two copies of native sampling/allocation hooks must not coexist.
        if (getServer().getPluginManager().getPlugin("spark")) {
            getLogger().error("OniProfiler was not started: standalone Spark is also installed. Stop the server, remove its plugin binary, and restart. Keep its data folder as a backup.");
            return;
        }
        try {
            const auto options = oni::Options::load(getDataFolder() / "oniprofiler.toml");
            std::string hash_error;
            const auto hash = spark::currentExecutableSha256(hash_error);
            if (hash.empty()) getLogger().warning("BDS executable identity unavailable: {}", hash_error);
            dispatcher_ = std::make_unique<spark::endstone_adapter::EndstoneDispatcher>(*this,getServer());
            metadata_ = std::make_unique<spark::endstone_adapter::EndstoneMetadataProvider>(*this,getServer(),hash);
            spark::SparkConfig config(getDataFolder()/"config.toml");
            if (!config.loadOrCreate()) throw std::runtime_error("Spark engine configuration: " + config.lastError());
            config.background_profiler_enabled=options.background_enabled;
            config.disable_response_broadcast=true;
            spark::TrustedViewersState viewers(getDataFolder()/"trusted-viewers.json"); viewers.load();
            notifier_=std::make_unique<spark::endstone_adapter::EndstoneNotifier>(*this,getServer(),true);
            app_=std::make_unique<spark::SparkApplication>(hash,spark::profileStorageDirectory(getDataFolder()),
                getDataFolder()/"activity.json",std::move(config),std::move(viewers),*dispatcher_,*metadata_,*notifier_);
            app_->statistics().start();
            app_->statistics().recordPlayerCount(static_cast<std::int64_t>(getServer().getOnlinePlayers().size()));
            app_->setMainThreadId(threadId());
            center_=std::make_unique<oni::ControlCenter>(*this,*app_,*metadata_,options);
            app_->enable();
            auto papi_api=getServer().getServiceManager().load<papi::PlaceholderAPI>(std::string(papi::PlaceholderAPI::ServiceName));
            papi_.enable(*this,std::move(papi_api),app_->statistics(),spark::kVersion);
            tick_task_=getServer().getScheduler().runTaskTimer(*this,[this]{ onServerTick(); },0,1);
            getLogger().info("OniProfiler {} powered by spark {} enabled. Open /oniprofiler. Native profiles default to local storage.",oni::version,spark::kVersion);
        } catch (const std::exception &e) {
            getLogger().error("OniProfiler startup failed: {}",e.what());
            onDisable();
        }
    }
    void onDisable() override
    {
        if (center_) center_->shutdown();
        papi_.disable(*this);
        if (app_) app_->shutdown();
        getServer().getScheduler().cancelTasks(*this); tick_task_.reset();
        std::string error;
        if (app_ && !app_->shutdownProfilerBackend(error)) {
            std::fprintf(stderr,"[OniProfiler] Native profiler could not safely unload: %s\n",error.c_str());
            std::abort(); // Preserve upstream's fail-safe against dangling native hooks.
        }
        center_.reset(); app_.reset();
    }
    bool onCommand(endstone::CommandSender &sender,const endstone::Command &command,const std::vector<std::string> &args) override
    {
        if (!app_ || !center_) { sender.sendErrorMessage("OniProfiler is inactive. Check its startup errors in the server log."); return true; }
        std::vector<std::string> tokens;
        for (const auto &arg:args) {
            auto part=spark::Arguments::tokenize(arg); tokens.insert(tokens.end(),part.begin(),part.end());
        }
        try {
            if (command.getName()=="spark") return center_->advanced(sender,std::move(tokens));
            return center_->command(sender,tokens);
        } catch (const std::exception &e) {
            getLogger().error("OniProfiler command failed: {}",e.what());
            sender.sendErrorMessage("The command failed. Review the server log; no success is assumed."); return true;
        }
    }
private:
    void onServerTick()
    {
        if (!app_ || !center_) return;
        const double mspt=getServer().getCurrentMillisecondsPerTick();
        app_->onTick(mspt);
        center_->tick(mspt);
    }
    std::shared_ptr<endstone::Task> tick_task_;
    std::unique_ptr<spark::endstone_adapter::EndstoneDispatcher> dispatcher_;
    std::unique_ptr<spark::endstone_adapter::EndstoneMetadataProvider> metadata_;
    std::unique_ptr<spark::endstone_adapter::EndstoneNotifier> notifier_;
    std::unique_ptr<spark::SparkApplication> app_;
    std::unique_ptr<oni::ControlCenter> center_;
    spark::endstone_adapter::PapiIntegration papi_;
};
ENDSTONE_PLUGIN("oniprofiler","1.0.0-rc.2",OniProfilerPlugin)
{
    description="OniProfiler powered by spark: guided native performance investigations.";
    authors={"TheN1NJ4LL0","ReallocAll (upstream spark port)"};
    prefix="OniProfiler";
    load=endstone::PluginLoadOrder::PostWorld;
    soft_depend={"papi"};
    command("oniprofiler").description("Open OniProfiler's control center").usages("/oniprofiler [args: message]").permissions("oniprofiler.view");
    command("oniprof").description("OniProfiler shortcut").usages("/oniprof [args: message]").permissions("oniprofiler.view");
    command("spark").description("Spark compatibility commands; local storage by default").usages("/spark [args: message]").permissions("oniprofiler.view");
    permission("oniprofiler.view").description("View the OniProfiler menu and health").default_(endstone::PermissionDefault::Operator);
    permission("oniprofiler.record").description("Start recordings and control your own").default_(endstone::PermissionDefault::Operator);
    permission("oniprofiler.reports").description("Read report locations and save health summaries").default_(endstone::PermissionDefault::Operator);
    permission("oniprofiler.locations").description("Inspect sensitive loaded-area coordinates and request scans").default_(endstone::PermissionDefault::Operator);
    permission("oniprofiler.manage").description("Change settings and control other owners' recordings").default_(endstone::PermissionDefault::Operator);
    permission("oniprofiler.advanced").description("Use advanced Spark commands and native allocation presets").default_(endstone::PermissionDefault::Operator);
    permission("oniprofiler.share").description("Explicitly approve external sharing when enabled").default_(endstone::PermissionDefault::Operator);
    permission("oniprofiler.alerts").description("Receive incident notifications").default_(endstone::PermissionDefault::Operator);
    // Retain the upstream registry's permissions for /spark compatibility.
    permission("endstone.command.spark").description("Spark compatibility umbrella").default_(endstone::PermissionDefault::Operator);
    permission("spark.profiler").description("Spark native profiler commands").default_(endstone::PermissionDefault::Operator);
    permission("spark.tps").description("Spark TPS commands").default_(endstone::PermissionDefault::Operator);
    permission("spark.ping").description("Spark ping commands").default_(endstone::PermissionDefault::Operator);
    permission("spark.health").description("Spark detailed health commands").default_(endstone::PermissionDefault::Operator);
    permission("spark.activity").description("Spark activity commands").default_(endstone::PermissionDefault::Operator);
    permission("spark.tickmonitor").description("Spark tick monitor commands").default_(endstone::PermissionDefault::Operator);
}
