/*  DownloadThread
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#ifndef PokemonAutomation_DownloadThread_H
#define PokemonAutomation_DownloadThread_H

#include <functional>
#include "Common/Cpp/CancellableScope.h"
#include "Common/Cpp/Concurrency/AsyncTask.h"
#include "Common/Cpp/Concurrency/ConditionVariable.h"
#include "Common/Cpp/Concurrency/Mutex.h"
#include "ResourceDownloadHelpers.h"


namespace PokemonAutomation{

//  Downloads a resource now, in the thread that calls it, if it is not there
//  yet (for a model that is loaded at its first use, not before a program
//  starts). The progress goes to the log. Throws FatalProgramException with
//  resource_download_failed_message() if it cannot: the program stops and says
//  why. Only one download at a time.
void download_resource_now(const std::string& resource_slug);


class DownloadThread : public CancellableScope{

public:
    struct Hooks {
        std::function<bool()> is_ready_to_start;
        std::function<void(bool success)> on_finished;
        // std::function<void(const DownloadedResourceMetadata&)> run_download;
        // std::function<void(bool success)> update_label;
        std::function<void()> report_failed;
        std::function<void(const char*)> report_exception_caught;
        std::function<void(uint64_t bytes_done, uint64_t total_bytes)> report_download_progress;
        std::function<void(uint64_t bytes_done, uint64_t total_bytes)> report_hash_progress;
        std::function<void(uint64_t bytes_done, uint64_t total_bytes)> report_unzip_progress;
    };

public:
    ~DownloadThread();
    DownloadThread(Hooks hooks, const DownloadedResourceMetadata& remote_metadata, Mutex& lock, ConditionVariable& cv);

public:
    void start_download_thread();

    // throws OperationCancelledException if the user cancels the action
    void run_download(DownloadedResourceMetadata resource_metadata);

    

private:
    Hooks m_hooks;
    DownloadedResourceMetadata m_remote_metadata;
    AsyncTask m_worker;

    Mutex& m_download_lock;
    ConditionVariable& m_download_cv;
};
}
#endif
