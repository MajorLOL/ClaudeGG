/*  DownloadThread
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include <iostream>
#include "Common/Cpp/ScopeExit.h"
#include "Common/Cpp/Filesystem/Filesystem.h"
#include "CommonFramework/GlobalAutoPaths.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/Exceptions/OperationFailedException.h"
#include "CommonFramework/Exceptions/FatalProgramException.h"
#include "CommonFramework/Tools/GlobalThreadPools.h"
#include "CommonFramework/Tools/FileDownloader.h"
#include "CommonFramework/Tools/FileUnzip.h"
#include "CommonFramework/Tools/FileHash.h"
#include "DownloadThread.h"

namespace PokemonAutomation{



DownloadThread::~DownloadThread(){
    // cout << "~DownloadThread" << endl;
    this->cancel();
    m_worker.wait_and_ignore_exceptions();
}
DownloadThread::DownloadThread(Hooks hooks, const DownloadedResourceMetadata& remote_metadata, Mutex& lock, ConditionVariable& cv)
    : m_hooks(std::move(hooks))
    , m_remote_metadata(remote_metadata)
    , m_download_lock(lock)
    , m_download_cv(cv)
{}

void DownloadThread::start_download_thread(){
    m_worker = GlobalThreadPools::unlimited_normal().dispatch_now_blocking(
    [this]{

        bool success = false;
        {
            std::unique_lock<Mutex> lock(m_download_lock);
            m_download_cv.wait(lock, [this] { return m_hooks.is_ready_to_start(); });

        }
        
        // runs when lambda is finished
        ScopeExit on_exit([&, this]{
            m_hooks.on_finished(success);
        });

        try{

            // Logger& logger = global_logger_tagged();
            // throw_and_log<OperationFailedException>(logger, ErrorReportMode::NO_ERROR_REPORT, 
            //         "Test");
            // throw InternalProgramError(nullptr, PA_CURRENT_FUNCTION, "Test."); 


            // std::this_thread::sleep_for(std::chrono::seconds(7));

            run_download(m_remote_metadata);

            std::cout << "Done Download" << std::endl;
            success = true;

        }catch(OperationCancelledException&){
            // user cancelled action
            success = false;

        }catch(OperationFailedException&){
            success = false;
            m_hooks.report_failed();
        }catch (const std::exception& e){
            std::string error_msg = "DownloadThread::start_download_thread: " + std::string(e.what());
            success = false;
            m_hooks.report_exception_caught(error_msg.c_str());
        } catch(...){
            success = false;
            m_hooks.report_exception_caught("DownloadThread::start_download_thread: Unknown exception. Report this as an error.");
        }

    }
    );

}

void DownloadThread::run_download(DownloadedResourceMetadata resource_metadata){
    Logger& logger = global_logger_tagged();
    // std::this_thread::sleep_for(std::chrono::seconds(5));

    std::string url = resource_metadata.url;
    std::string resource_name = resource_metadata.resource_name;
    uint64_t expected_size = resource_metadata.size_compressed_bytes;

    std::string resource_directory = DOWNLOADED_RESOURCE_PATH() + resource_name;
    try{

        // delete directory and the old resource
        Filesystem::remove_all(resource_directory);

        // download
        std::string zip_path = resource_directory + "/temp.zip";
        FileDownloader::download_file_to_disk(
            *this,
            logger, 
            url, 
            zip_path,
            expected_size,
            [this](uint64_t bytes_done, uint64_t total_bytes){
                m_hooks.report_download_progress(bytes_done, total_bytes);
            }
        );

        // hash
        std::string hash = 
            hash_file(
                this,
                zip_path,
                [this](uint64_t bytes_done, uint64_t total_bytes){
                    m_hooks.report_hash_progress(bytes_done, total_bytes);
                }
            );
        std::string expected_hash = resource_metadata.sha256;
        if (hash != expected_hash){
            std::cerr << "current hash: " << hash << std::endl;
            throw_and_log<OperationFailedException>(
                logger,
                ErrorReportMode::NO_ERROR_REPORT,
                "Downloaded file failed verification. SHA 256 hash did not match the expected value."
            );
        }

        // Filesystem::Path p{zip_path};
        // cout << "File size: " << std::filesystem::file_size(p) << endl;

        // unzip
        unzip_file(
            *this,
            zip_path.c_str(), 
            resource_directory.c_str(),
            [this](uint64_t bytes_done, uint64_t total_bytes){
                m_hooks.report_unzip_progress(bytes_done, total_bytes);
            }
        );

        // delete old zip file
        Filesystem::remove(zip_path);

        throw_if_cancelled();

    }catch(OperationCancelledException&){
        // delete directory and the resource
        Filesystem::remove_all(resource_directory);

        throw;
    }catch(OperationFailedException&){
        // delete directory and the resource
        Filesystem::remove_all(resource_directory);

        throw;
    }catch(...){
        // delete directory and the resource
        Filesystem::remove_all(resource_directory);

        throw;
    }

}


void download_resource_now(const std::string& resource_slug){
    static Mutex one_at_a_time;
    std::lock_guard<Mutex> lg(one_at_a_time);

    Logger& logger = global_logger_tagged();
    if (!all_resource_names().contains(resource_slug)){
        throw FatalProgramException(
            ErrorReportMode::NO_ERROR_REPORT,
            "Claude GG needs " + resource_slug + ", but this package does not say where to download it. "
            "Download the newest Claude GG, or put the files in the folder " + DOWNLOADED_RESOURCE_PATH() + resource_slug + "."
        );
    }
    if (get_local_version_info(resource_slug).version_status == ResourceVersionStatus::CURRENT){
        return;     //  Another thread downloaded it while this one waited.
    }

    std::string reason;
    try{
        DownloadedResourceMetadata metadata = get_remote_resource_metadata_from_resource_slug(resource_slug);
        logger.log(
            "Downloading " + resource_slug + " (" + std::to_string(metadata.size_compressed_bytes / 1000000) +
            " MB) at its first use: " + metadata.url, COLOR_BLUE
        );
        auto progress = [&logger, &resource_slug, last = -1](const char* step, uint64_t done, uint64_t total) mutable{
            if (total == 0){
                return;
            }
            int percent = (int)(done * 100 / total);
            if (percent / 10 != last / 10 || (percent == 100 && last != 100)){
                last = percent;
                logger.log(resource_slug + ": " + step + " " + std::to_string(percent) + "%");
            }
        };
        DownloadThread::Hooks hooks{
            .is_ready_to_start = []{ return true; },
            .on_finished = [](bool){},
            .report_failed = []{},
            .report_exception_caught = [](const char*){},
            .report_download_progress = [&](uint64_t done, uint64_t total){ progress("downloading", done, total); },
            .report_hash_progress = [](uint64_t, uint64_t){},
            .report_unzip_progress = [&](uint64_t done, uint64_t total){ progress("unpacking", done, total); },
        };
        Mutex lock;
        ConditionVariable cv;
        DownloadThread download(std::move(hooks), metadata, lock, cv);
        download.run_download(metadata);
        if (get_local_version_info(resource_slug).version_status == ResourceVersionStatus::NOT_APPLICABLE){
            reason = "the zip has no version.json.";
        }else{
            logger.log("Downloaded " + resource_slug + ".", COLOR_BLUE);
            return;
        }
    }catch (OperationFailedException& e){
        reason = e.message();
    }catch (OperationCancelledException&){
        reason = "the download was stopped.";
    }catch (const std::exception& e){
        reason = e.what();
    }
    logger.log("Download of " + resource_slug + " failed: " + reason, COLOR_RED);
    throw FatalProgramException(ErrorReportMode::NO_ERROR_REPORT, resource_download_failed_message(resource_slug, reason));
}


}
