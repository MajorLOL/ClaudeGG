/*  Claude GG Pi Card (an SD card for the Raspberry Pi of a phone: Raspberry Pi OS, and the agent installs itself)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  The window "Prepare an SD card" of the page of the Raspberry Pi in the setup: the name of the Pi, its user and password, the
 *  Wi-Fi, and the SD card.  "Run":
 *
 *  1. asks once more, with the name and size of the card, before anything is erased (only removable drives are offered: USB, SD and
 *     MMC, never the drive Windows starts from);
 *  2. writes Raspberry Pi OS Lite (64-bit) to it with Raspberry Pi Imager (its command line, "rpi-imager --cli"; Windows asks for the
 *     rights of an administrator);
 *  3. puts on the boot partition (the drive with cmdline.txt and config.txt, "bootfs"):
 *     - user-data: the cloud-init file that Raspberry Pi OS 13 (Trixie) reads at its first start, with the name of the Pi and the user
 *       (no password in it), and one command: claudegg/firstboot.sh;
 *     - claudegg/settings: the password, the Wi-Fi and the token of the agent, one per line.  firstboot.sh reads it and removes it;
 *     - claudegg/firstboot.sh: sets the password, the Wi-Fi and SSH, waits for the network, clones Claude GG and runs
 *       Mobile/agent/install-agent.sh as the user, with the token that Claude GG made or already had (so the connection that was
 *       set up keeps working).  What it says is written to claudegg/install.log on the card;
 *  4. fills in "<name>.local" and the token on the page.
 *
 *  The Claude API key of Claude GG is not put on the card: the Pi does no thinking of its own.
 *
 *  Experimental: not tried on a real Raspberry Pi or SD card yet.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_PiCard_H
#define PokemonAutomation_ClaudeGG_PiCard_H

#include <functional>
#include <vector>
#include <QString>
#include <QStringList>

class QWidget;

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PiCard{


struct Settings{
    QString hostname = "claudegg";
    QString user = "claudegg";
    QString password;
    QString wifi_name;          //  empty: a network cable
    QString wifi_password;
    QString country = "NL";     //  of the Wi-Fi (two letters)
    QString token;              //  of the agent (at least 16 characters)
};

//  What is wrong with the settings, in English (empty: nothing).
QString problem(const Settings& settings);

//  The files of the boot partition.
QString user_data(const Settings& settings);
QString settings_file(const Settings& settings);
QString firstboot_script();

//  A new token for the agent (32 hex digits, as the agent makes them).
QString new_token();

//  The roots of the mounted drives that are the boot partition of a Raspberry Pi (cmdline.txt and config.txt there).
QStringList find_boot_partitions();
//  Writes the files to the boot partition at `root`.  False and `error` when a file could not be written.
bool write_boot_partition(const QString& root, const Settings& settings, QString& error);

//  A drive that can be erased: only removable ones.
struct Disk{
    QString device;             //  \\.\PhysicalDrive2, /dev/sdb
    QString name;               //  as the system names it
    double gigabytes = 0;
};
std::vector<Disk> removable_disks(QString* error = nullptr);
//  Raspberry Pi Imager on this computer (empty: not installed).
QString imager_path();

//  The window.  `token`: the token of the agent that is filled in already (empty: a new one is made).  `done` is called with the
//  address and the token when the card is ready.
void open_dialog(QWidget* parent, const QString& token, const std::function<void(const QString& host, const QString& token)>& done);

//  The check of the files (no drive is touched): the lines of what went wrong; the number of them is returned.
int run_checks(QStringList& report);


}
}
}
#endif
