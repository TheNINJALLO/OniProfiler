// SPDX-License-Identifier: GPL-3.0-only
#include "oni/domain.h"
#include "oni/report_writer.h"
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

namespace fs = std::filesystem;
static int checks = 0;
void check(bool good, const char *message) { ++checks; if (!good) throw std::runtime_error(message); }
std::string read(const fs::path &path) { std::ifstream in(path); return {std::istreambuf_iterator<char>(in), {}}; }

int main()
{
    const auto root = fs::temp_directory_path() / ("oniprofiler-tests-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    try {
        using namespace oni;
        check(quote("\"\\\n\t\r") == "\"\\\"\\\\\\n\\t\\r\"", "JSON escaping");
        check(quote(std::string(1,'\x01')) == "\"\\u0001\"", "JSON control escaping");
        check(quote("entity:example") == "\"entity:example\"", "JSON simple string");
        check(number(std::nullopt) == "null", "Missing number is null");
        check(number(std::numeric_limits<double>::infinity()) == "null", "Infinite number is null");
        check(number(std::numeric_limits<double>::quiet_NaN()) == "null", "NaN is null");
        check(number(0.0) == "0", "Measured zero remains zero");
        check(fixed(std::nullopt) == "Unavailable", "Unavailable formatted value");
        check(fixed(12.25,2) == "12.25", "Number formatting");
        Health h;
        check(explain(h).front().level == "unknown", "Missing baseline is not healthy");
        h.history_ms=10000; h.tick_samples=200; h.tps=20; h.mspt_mean=25; h.mspt_p95=40; h.mspt_max=49;
        check(explain(h).front().level == "ok", "Valid recent measurements");
        h.history_ms=9999;
        check(explain(h).front().level == "unknown", "Warmup boundary");
        h.history_ms=10000; h.tick_samples=19;
        check(explain(h).front().level == "unknown", "Too few samples");
        h.tick_samples=200; h.tps=17;
        check(explain(h).front().level == "critical", "Low TPS");
        h.tps=20; h.mspt_mean=51;
        check(explain(h).front().level == "critical", "Mean over budget");
        h.mspt_mean=20; h.mspt_p95=51;
        check(explain(h).front().level == "warning", "Slow upper percentile");
        h.mspt_p95=40; h.mspt_max=251;
        check(explain(h).size()==2, "Long tick finding");
        h.cpu_percent=0; h.rss_bytes=1024;
        check(explain(h).size()==4, "CPU/memory limitations retained for zero CPU");
        check(healthJson(h).find("\"entities\":null")!=std::string::npos, "Unknown entity count isn't zero");
        h.entities=0;
        check(healthJson(h).find("\"entities\":0")!=std::string::npos, "Measured entity zero");
        h.tps=std::numeric_limits<double>::quiet_NaN();
        check(explain(h).front().level=="unknown", "Invalid TPS not healthy");
        std::vector<Area> areas={{"z",0,0,2,{}},{"a",0,0,2,{}},{"b",-1,2,10,{}}};
        rankAreas(areas,2);
        check(areas.size()==2 && areas[0].entities==10 && areas[1].dimension=="a", "Stable ranking limit");
        check(areasJson(areas,123).find("\"chunk_x\":-1")!=std::string::npos, "Negative chunk coordinates");
        rankAreas(areas,0);
        check(areas.empty(), "Zero ranking limit");
        IncidentDetector detector;
        check(!detector.observe(120,0), "Incident starts a window");
        check(!detector.observe(120,4999), "Incident below sustained duration");
        check(detector.observe(120,5000), "Incident at duration boundary");
        check(!detector.observe(120,10000), "Incident cooldown");
        check(!detector.observe(20,304999), "Healthy tick resets streak");
        check(!detector.observe(120,305000), "New streak starts after recovery");
        check(detector.observe(120,310000), "New incident after cooldown");
        check(!detector.observe(std::numeric_limits<double>::quiet_NaN(),311000), "Invalid tick resets streak");
        check(!detector.observe(120,312000), "No trigger after invalid tick");
        check(!detector.observe(120,0), "Clock rollback resets safely");
        check(detector.observe(120,5000), "Clock rollback recovery");
        check(mayControl("a","a",true,false,1,1), "Recording owner can stop");
        check(!mayControl("b","a",true,false,1,1), "Other staff cannot stop");
        check(mayControl("b","a",false,true,1,1), "Manager can stop");
        check(!mayControl("b","a",true,true,1,2), "Stale menu rejected for manager");
        check(!mayControl("a","a",true,true,0,0), "No-session rejected");
        check(!mayControl("a","a",false,false,1,1), "Revoked permission rejected");
        for (const auto &p:presets()) {
            const auto tokens=presetTokens(p,"test comment");
            check(std::find(tokens.begin(),tokens.end(),"--save-to-file")!=tokens.end(), "Every preset stays local");
            check(p.seconds>10, "Every preset exceeds native minimum timeout");
        }
        check(classifyAdvanced({"profiler","--stop"}).mutates, "Legacy stop checked for ownership");
        check(classifyAdvanced({"sampler","--stop"}).force_local, "Legacy stop stays local");
        check(classifyAdvanced({"profiler","--upload"}).external, "Legacy upload needs sharing gate");
        check(classifyAdvanced({"profiler","start","--stop"}).mutates, "Mixed start/stop cannot bypass ownership");
        check(classifyAdvanced({"profiler","start"}).starts, "Start requires recording permission");
        check(classifyAdvanced({"health","--upload"}).external, "Health upload needs sharing gate");
        check(!classifyAdvanced({"tps"}).external, "Reading metrics isn't external sharing");
        check(classifyAdvanced({"profiler","--stop=true"}).mutates, "Equals-syntax cannot bypass ownership");
        check(classifyAdvanced({"health","--upload=true"}).external, "Equals-syntax cannot bypass sharing policy");
        check(!classifyAdvanced({"profiler","start","--comment","open"}).external, "A plain comment isn't live sharing");
        check(ReportWriter::validId("123-1"), "Safe report ID");
        check(!ReportWriter::validId("../../outside"), "Path traversal rejected");
        check(!ReportWriter::validId("X"), "Unexpected report ID rejected");
        check(!ReportWriter::validId(std::string(81,'a')), "Oversized report ID rejected");
        fs::create_directories(root / "profiles");
        { std::ofstream out(root/"profiles"/"native.sparkprofile"); out<<"12345"; }
        {
            ReportWriter writer(root/"reports",10);
            check(!writer.report("../bad","{}"), "Unsafe writes not queued");
            for(int i=0;i<12;++i) check(writer.report("100"+std::to_string(i),"{\"ok\":true}"), "Bounded report submission");
            writer.dashboard("{\"timestamp\":1}");
            writer.dashboard("{\"timestamp\":2}");
            writer.stop();
            check(writer.takeError().empty(), "Async writes succeed");
            check(!writer.report("after-stop","{}"), "Stopped writer rejects submission");
            check(writer.diskMeasured() && writer.profileBytes()==5, "Storage budget measurement");
        }
        check(read(root/"reports"/"dashboard.json")=="{\"timestamp\":2}", "Latest dashboard replaces old snapshot");
        int count=0; for(const auto &e:fs::directory_iterator(root/"reports")) if(e.path().filename().string().starts_with("report-")) ++count;
        check(count==10, "Summary retention enforced");
        check(fs::exists(root/"profiles"/"native.sparkprofile"), "Native profiles are never auto-deleted");
        std::error_code ec;
        fs::create_symlink(root/"profiles"/"native.sparkprofile",root/"reports"/"report-symlink.json",ec);
        if(!ec) {
            ReportWriter writer(root/"reports",10);
            check(writer.report("symlink","overwrite"), "Symlink test queued"); writer.stop();
            check(!writer.takeError().empty(), "Report symlink rejected");
            check(read(root/"profiles"/"native.sparkprofile")=="12345", "Symlink target unchanged");
        }
        fs::remove_all(root);
        std::cout<<"Passed "<<checks<<" C++ checks. No BDS runtime was used.\n";
        return 0;
    } catch(const std::exception &e) { fs::remove_all(root); std::cerr<<"FAIL after "<<checks<<" checks: "<<e.what()<<'\n'; return 1; }
}
