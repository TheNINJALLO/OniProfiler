// SPDX-License-Identifier: GPL-3.0-only
#include "oni/command_bridge.h"
#include "oni/domain.h"
#include <algorithm>
#include <chrono>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <vector>
namespace oni {
namespace {
std::int64_t wallMs() { return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count(); }
void ensureFolder(const std::filesystem::path &p) {
    if (std::filesystem::is_symlink(p)) throw std::runtime_error("Bridge directory must not be a symlink");
    std::filesystem::create_directories(p);
#ifndef _WIN32
    std::filesystem::permissions(p, std::filesystem::perms::owner_all, std::filesystem::perm_options::replace);
#endif
}
}
CommandBridge::CommandBridge(std::filesystem::path root):root_(std::move(root)),thread_([this]{worker();}) {}
CommandBridge::~CommandBridge(){stop();}
void CommandBridge::stop(){ {std::lock_guard lock(mutex_);stopping_=true;wake_.notify_all();} if(thread_.joinable())thread_.join(); }
std::optional<RemoteCommand> CommandBridge::pop(){
    std::lock_guard lock(mutex_); if(failed_ || incoming_.empty()) return {};
    auto command=std::move(incoming_.front());incoming_.pop_front();return command;
}
void CommandBridge::acknowledge(std::string id,std::string status,std::string message,std::int64_t session){
    std::lock_guard lock(mutex_);
    if (outgoing_.size()>=64) {error_="Bridge acknowledgement queue is full; request outcome is indeterminate";return;}
    outgoing_.push_back({std::move(id),std::move(status),std::move(message),session});wake_.notify_all();
}
std::string CommandBridge::takeError(){std::lock_guard lock(mutex_);return std::exchange(error_,{});}
void CommandBridge::recover(){
    for(const auto &e:std::filesystem::directory_iterator(root_/"claimed")){
        if(e.is_symlink()||!e.is_regular_file()||e.path().extension()!=".cmd")continue;
        const auto id=e.path().stem().string();
        if(bridgeId(id)&&!std::filesystem::exists(root_/"outbox"/(id+".json")))
            { acknowledge(id,"indeterminate","Server stopped after claiming this request. It will not be replayed."); flush(); }
    }
    flush();
}
void CommandBridge::scan(){
    std::size_t scanned=0;
    for(const auto &e:std::filesystem::directory_iterator(root_/"inbox")){
        if(++scanned>32)break;
        {std::lock_guard lock(mutex_);if(incoming_.size()>=16)break;}
        if(e.is_symlink()||!e.is_regular_file()||e.path().extension()!=".cmd")continue;
        const auto id=e.path().stem().string();if(!bridgeId(id))continue;
        if(std::filesystem::exists(root_/"outbox"/(id+".json"))||std::filesystem::exists(root_/"claimed"/(id+".cmd"))){
            std::filesystem::remove(e.path());continue;
        }
        const auto destination=root_/"claimed"/(id+".cmd");
        // Claim durably before queueing. A restart must never repeat a profiler action.
        std::filesystem::rename(e.path(),destination);
        if(std::filesystem::file_size(destination)>4096){acknowledge(id,"rejected","Request exceeds the size limit");continue;}
        std::ifstream stream(destination,std::ios::binary);
        std::string content((std::istreambuf_iterator<char>(stream)),{}),error;
        auto command=parseRemote(content,error);
        if(!command||command->id!=id){acknowledge(id,"rejected",command?"File identity mismatch":error);continue;}
        std::lock_guard lock(mutex_);incoming_.push_back(std::move(*command));
    }
}
void CommandBridge::flush(){
    std::deque<Ack> acks;{std::lock_guard lock(mutex_);acks.swap(outgoing_);}
    for(const auto &a:acks){
        const auto destination=root_/"outbox"/(a.id+".json");
        if(std::filesystem::exists(destination))continue; // Immutable first outcome.
        auto temporary=destination;temporary+=".tmp";
        if(std::filesystem::is_symlink(temporary))throw std::runtime_error("Bridge temporary file is a symlink");
        std::ofstream out(temporary,std::ios::binary|std::ios::trunc);out.exceptions(std::ios::badbit|std::ios::failbit);
        out<<"{\"id\":"<<quote(a.id)<<",\"status\":"<<quote(a.status)<<",\"message\":"<<quote(a.message)
           <<",\"session\":"<<a.session<<",\"completed_ms\":"<<wallMs()<<"}";
        out.flush();out.close();std::filesystem::rename(temporary,destination);
    }
}
void CommandBridge::prune(){
    // Retain terminal outcomes for 24 h. Requests have a <=3 minute lifetime.
    const auto cutoff=std::filesystem::file_time_type::clock::now()-std::chrono::hours(24);
    for(const auto *name:{"outbox","claimed"})
        for(const auto &e:std::filesystem::directory_iterator(root_/name))
            if(!e.is_symlink()&&e.is_regular_file()&&bridgeId(e.path().stem().string())&&e.last_write_time()<cutoff)
                std::filesystem::remove(e.path());
}
void CommandBridge::worker() noexcept{
    try{
        ensureFolder(root_);for(const auto *name:{"inbox","claimed","outbox"})ensureFolder(root_/name);
        recover();auto next_prune=std::chrono::steady_clock::now();
        for(;;){
            bool done;{std::unique_lock lock(mutex_);wake_.wait_for(lock,std::chrono::milliseconds(250),[&]{return stopping_||!outgoing_.empty();});done=stopping_;}
            flush();if(done)break;
            scan();
            if(std::chrono::steady_clock::now()>=next_prune){prune();next_prune=std::chrono::steady_clock::now()+std::chrono::minutes(5);}
        }
    }catch(const std::exception &e){std::lock_guard lock(mutex_);error_=e.what();failed_=true;incoming_.clear();}
}
}
