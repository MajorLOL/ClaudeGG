/*  Claude GG Pi Card (an SD card for the Raspberry Pi of a phone: Raspberry Pi OS, and the agent installs itself)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  See ClaudeGG_PiCard.h.
 *
 */

#include <memory>
#include <QCheckBox>
#include <QComboBox>
#include <QDesktopServices>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFormLayout>
#include <QHash>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QProcess>
#include <QProgressBar>
#include <QPushButton>
#include <QRandomGenerator>
#include <QRegularExpression>
#include <QStandardPaths>
#include <QStorageInfo>
#include <QTimer>
#include <QUrl>
#include <QVBoxLayout>
#include "ClaudeGG_Language.h"
#include "ClaudeGG_PiCard.h"

namespace PokemonAutomation{
namespace ClaudeGG{
namespace PiCard{

namespace{

const char* const IMAGE_URL = "https://downloads.raspberrypi.com/raspios_lite_arm64_latest";
const char* const IMAGER_PAGE = "https://www.raspberrypi.com/software/";
const char* const MARK = "claudegg/firstboot.sh";
const int CARD_WAIT_SECONDS = 180;      //  after the image is written: how long the boot partition is waited for

bool one_line(const QString& text){
    return !text.contains('\n') && !text.contains('\r');
}

bool write_file(const QString& path, const QString& text, QString& error){
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)){
        error = path + ": " + file.errorString();
        return false;
    }
    const QByteArray bytes = text.toUtf8();
    if (file.write(bytes) != bytes.size()){
        error = path + ": " + file.errorString();
        return false;
    }
    file.close();
    return true;
}

QString random_hex(int bytes){
    QString out;
    for (int c = 0; c < bytes; c++){
        out += QString("%1").arg(QRandomGenerator::system()->bounded(256), 2, 16, QChar('0'));
    }
    return out;
}

}


QString problem(const Settings& settings){
    static const QRegularExpression HOSTNAME("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$");
    static const QRegularExpression USER("^[a-z_][a-z0-9_-]{0,31}$");
    static const QRegularExpression COUNTRY("^[A-Z]{2}$");
    static const QRegularExpression TOKEN("^[A-Za-z0-9_-]{16,128}$");
    if (!HOSTNAME.match(settings.hostname).hasMatch()){
        return "The name of the Pi may only have small letters, digits and '-'.";
    }
    if (!USER.match(settings.user).hasMatch() || settings.user == "root"){
        return "The user may only have small letters, digits, '_' and '-', and cannot be root.";
    }
    if (settings.password.isEmpty() || !one_line(settings.password)){
        return "Choose a password for the user.";
    }
    if (!one_line(settings.wifi_name) || settings.wifi_name.toUtf8().size() > 32){
        return "The name of the Wi-Fi is too long.";
    }
    if (!settings.wifi_name.isEmpty() && !settings.wifi_password.isEmpty()
        && (settings.wifi_password.size() < 8 || settings.wifi_password.size() > 63 || !one_line(settings.wifi_password))){
        return "A Wi-Fi password has 8 to 63 characters.";
    }
    if (!COUNTRY.match(settings.country).hasMatch()){
        return "The country of the Wi-Fi is two letters, such as NL.";
    }
    if (!TOKEN.match(settings.token).hasMatch()){
        return "The token of the agent must be 16 or more letters and digits.";
    }
    return QString();
}

QString user_data(const Settings& settings){
    //  No password in here: firstboot.sh sets it from claudegg/settings, which it removes.
    return QString(
        "#cloud-config\n"
        "# Written by Claude GG: the agent of the phone installs itself at the first start (claudegg/firstboot.sh).\n"
        "hostname: %1\n"
        "manage_etc_hosts: true\n"
        "users:\n"
        "  - name: %2\n"
        "    groups: users,adm,dialout,audio,netdev,video,plugdev,input,gpio,sudo\n"
        "    shell: /bin/bash\n"
        "    lock_passwd: false\n"
        "    sudo: ALL=(ALL) NOPASSWD:ALL\n"
        "ssh_pwauth: true\n"
        "runcmd:\n"
        "  - [bash, /boot/firmware/%3]\n"
    ).arg(settings.hostname, settings.user, QString(MARK));
}

QString settings_file(const Settings& settings){
    //  One per line, read with "read -r" (never run): the password, the Wi-Fi, its password, the country, the token.
    return settings.password + "\n" + settings.wifi_name + "\n" + settings.wifi_password + "\n" + settings.country + "\n" + settings.token + "\n";
}

QString firstboot_script(){
    return QString(
        "#!/bin/bash\n"
        "# Claude GG: the first start of this Raspberry Pi (run once by cloud-init, as root).\n"
        "# It sets the password, the Wi-Fi and SSH, and installs the agent of the phone (Mobile/agent of Claude GG).\n"
        "CARD=\"$(dirname \"$(readlink -f \"$0\")\")\"\n"
        "exec >>\"$CARD/install.log\" 2>&1\n"
        "echo \"== $(date) Claude GG: first start ==\"\n"
        "U=\"$(getent passwd 1000 | cut -d: -f1)\"\n"
        "if [ -z \"$U\" ]; then echo \"There is no user: prepare the card again in Claude GG.\"; exit 1; fi\n"
        "H=\"$(getent passwd \"$U\" | cut -d: -f6)\"\n"
        "G=\"$(id -gn \"$U\")\"\n"
        "PASSWORD=\"\"; WIFI=\"\"; WIFI_PASSWORD=\"\"; COUNTRY=\"\"; TOKEN=\"\"\n"
        "if [ -f \"$CARD/settings\" ]; then\n"
        "  { IFS= read -r PASSWORD; IFS= read -r WIFI; IFS= read -r WIFI_PASSWORD; IFS= read -r COUNTRY; IFS= read -r TOKEN; } < \"$CARD/settings\"\n"
        "  rm -f \"$CARD/settings\"\n"
        "fi\n"
        "if [ -n \"$PASSWORD\" ]; then\n"
        "  printf '%s:%s\\n' \"$U\" \"$PASSWORD\" | chpasswd && echo \"The password of $U is set.\"\n"
        "fi\n"
        "if [ -n \"$COUNTRY\" ]; then raspi-config nonint do_wifi_country \"$COUNTRY\" || true; fi\n"
        "rfkill unblock wifi || true\n"
        "if [ -n \"$WIFI\" ]; then\n"
        "  for i in $(seq 1 30); do nmcli -t general status >/dev/null 2>&1 && break; sleep 2; done\n"
        "  nmcli connection delete claudegg-wifi >/dev/null 2>&1 || true\n"
        "  if [ -n \"$WIFI_PASSWORD\" ]; then\n"
        "    nmcli connection add type wifi ifname wlan0 con-name claudegg-wifi autoconnect yes ssid \"$WIFI\" wifi-sec.key-mgmt wpa-psk wifi-sec.psk \"$WIFI_PASSWORD\"\n"
        "  else\n"
        "    nmcli connection add type wifi ifname wlan0 con-name claudegg-wifi autoconnect yes ssid \"$WIFI\"\n"
        "  fi\n"
        "  nmcli connection up claudegg-wifi || true\n"
        "fi\n"
        "systemctl enable --now ssh && echo \"SSH is on.\"\n"
        "echo \"Waiting for the network...\"\n"
        "for i in $(seq 1 120); do getent hosts github.com >/dev/null && break; sleep 10; done\n"
        "apt-get update && apt-get install -y git || { echo \"git could not be installed: is the Pi on the network?\"; exit 1; }\n"
        "if [ -n \"$TOKEN\" ]; then\n"
        "  install -d -m 700 -o \"$U\" -g \"$G\" \"$H/.claudegg-agent\"\n"
        "  printf '%s\\n' \"$TOKEN\" > \"$H/.claudegg-agent/token\"\n"
        "  chown \"$U:$G\" \"$H/.claudegg-agent/token\"\n"
        "  chmod 600 \"$H/.claudegg-agent/token\"\n"
        "fi\n"
        "if [ ! -d \"$H/ClaudeGG\" ]; then\n"
        "  sudo -u \"$U\" -H git clone --depth 1 https://github.com/MajorLOL/ClaudeGG \"$H/ClaudeGG\" || { echo \"Claude GG could not be downloaded.\"; exit 1; }\n"
        "fi\n"
        "cd \"$H\" && sudo -u \"$U\" -H bash \"$H/ClaudeGG/Mobile/agent/install-agent.sh\"\n"
        "echo \"== $(date) Claude GG: done ($?) ==\"\n"
    );
}

QString new_token(){
    return random_hex(16);
}


QStringList find_boot_partitions(){
    QStringList out;
    for (const QStorageInfo& volume : QStorageInfo::mountedVolumes()){
        if (!volume.isValid() || !volume.isReady() || volume.isReadOnly()){
            continue;
        }
        const QDir root(volume.rootPath());
        if (root.exists("cmdline.txt") && root.exists("config.txt")){
            out << volume.rootPath();
        }
    }
    return out;
}

bool write_boot_partition(const QString& root, const Settings& settings, QString& error){
    const QDir dir(root);
    if (!dir.exists("cmdline.txt") || !dir.exists("config.txt")){
        error = root + ": this is not the boot partition of a Raspberry Pi.";
        return false;
    }
    if (!dir.exists("claudegg") && !QDir(root).mkdir("claudegg")){
        error = root + ": the folder claudegg could not be made.";
        return false;
    }
    //  A new instance-id: cloud-init takes the card for a new Pi and runs user-data again (also on a card that started before).
    return write_file(dir.filePath("claudegg/firstboot.sh"), firstboot_script(), error)
        && write_file(dir.filePath("claudegg/settings"), settings_file(settings), error)
        && write_file(dir.filePath("meta-data"), "instance-id: claudegg-" + random_hex(8) + "\n", error)
        && write_file(dir.filePath("user-data"), user_data(settings), error);
}


std::vector<Disk> removable_disks(QString* error){
    std::vector<Disk> out;
    QProcess process;
#ifdef _WIN32
    //  USB, SD and MMC disks, never the one Windows starts from or lives on.
    process.start("powershell", {"-NoProfile", "-NonInteractive", "-Command",
        "Get-Disk | Where-Object { ($_.BusType -eq 'USB' -or $_.BusType -eq 'SD' -or $_.BusType -eq 'MMC') -and -not $_.IsBoot -and -not $_.IsSystem }"
        " | ForEach-Object { \"$($_.Number)`t$($_.FriendlyName)`t$($_.Size)\" }"});
#else
    process.start("lsblk", {"-d", "-b", "-n", "-P", "-o", "NAME,SIZE,RM,TRAN,MODEL,TYPE"});
#endif
    if (!process.waitForFinished(20000) || process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0){
        if (error != nullptr){
            *error = QString::fromLocal8Bit(process.readAllStandardError()).trimmed();
            if (error->isEmpty()){
                *error = process.errorString();
            }
        }
        return out;
    }
    const QStringList lines = QString::fromLocal8Bit(process.readAllStandardOutput()).split('\n', Qt::SkipEmptyParts);
    for (const QString& raw : lines){
        const QString line = raw.trimmed();
#ifdef _WIN32
        const QStringList parts = line.split('\t');
        bool number_ok = false;
        const int number = parts.value(0).toInt(&number_ok);
        if (parts.size() < 3 || !number_ok){
            continue;
        }
        out.push_back(Disk{"\\\\.\\PhysicalDrive" + QString::number(number), parts[1].trimmed(), parts[2].toDouble() / 1e9});
#else
        static const QRegularExpression PAIR("(\\w+)=\"([^\"]*)\"");
        QHash<QString, QString> values;
        auto it = PAIR.globalMatch(line);
        while (it.hasNext()){
            const QRegularExpressionMatch match = it.next();
            values[match.captured(1)] = match.captured(2);
        }
        if (values.value("TYPE") != "disk" || (values.value("RM") != "1" && values.value("TRAN") != "usb" && values.value("TRAN") != "mmc")){
            continue;
        }
        out.push_back(Disk{"/dev/" + values.value("NAME"), values.value("MODEL").trimmed(), values.value("SIZE").toDouble() / 1e9});
#endif
    }
    return out;
}

QString imager_path(){
#ifdef _WIN32
    for (const char* variable : {"ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"}){
        const QString base = qEnvironmentVariable(variable);
        if (base.isEmpty()){
            continue;
        }
        for (const char* folder : {"Raspberry Pi Imager", "Programs/Raspberry Pi Imager"}){
            const QString path = QDir(base).filePath(QString(folder) + "/rpi-imager.exe");
            if (QFileInfo::exists(path)){
                return QDir::toNativeSeparators(path);
            }
        }
    }
    return QStandardPaths::findExecutable("rpi-imager");
#else
    return QStandardPaths::findExecutable("rpi-imager");
#endif
}


namespace{

//  The window of the card: the fields, the drive, Run, and what is going on.
class CardDialog : public QDialog{
public:
    CardDialog(QWidget* parent, const QString& token, const std::function<void(const QString&, const QString&)>& done)
        : QDialog(parent)
        , m_token(token)
        , m_done(done)
    {
        setWindowTitle(tr_ui("Prepare an SD card"));
        setMinimumWidth(560);
        QVBoxLayout* layout = new QVBoxLayout(this);
        QLabel* intro = new QLabel(tr_ui("Claude GG writes Raspberry Pi OS Lite to the SD card with Raspberry Pi Imager, with these settings. The first time the Raspberry Pi starts, it installs the Claude GG agent by itself (about 10 to 15 minutes)."), this);
        intro->setWordWrap(true);
        layout->addWidget(intro);

        QFormLayout* form = new QFormLayout();
        m_hostname = add_field(form, tr_ui("Name of the Raspberry Pi"), "claudegg");
        m_user = add_field(form, tr_ui("User"), "claudegg");
        m_password = add_field(form, tr_ui("Password"), "");
        m_password->setEchoMode(QLineEdit::Password);
        m_wifi = add_field(form, tr_ui("Wi-Fi name"), "");
        m_wifi->setPlaceholderText(tr_ui("Empty: a network cable"));
        m_wifi_password = add_field(form, tr_ui("Wi-Fi password"), "");
        m_wifi_password->setEchoMode(QLineEdit::Password);
        m_country = add_field(form, tr_ui("Country of the Wi-Fi"), "NL");
        m_country->setMaxLength(2);

        QHBoxLayout* disk_row = new QHBoxLayout();
        m_disks = new QComboBox(this);
        disk_row->addWidget(m_disks, 1);
        QPushButton* refresh = new QPushButton(tr_ui("Look again"), this);
        disk_row->addWidget(refresh);
        form->addRow(tr_ui("SD card"), disk_row);
        layout->addLayout(form);

        m_only_settings = new QCheckBox(tr_ui("Raspberry Pi OS is on the card already: only add the settings"), this);
        layout->addWidget(m_only_settings);

        m_busy = new QProgressBar(this);
        m_busy->setRange(0, 0);
        m_busy->hide();
        layout->addWidget(m_busy);
        m_status = new QLabel(this);
        m_status->setWordWrap(true);
        m_status->setTextInteractionFlags(Qt::TextSelectableByMouse);
        layout->addWidget(m_status);

        QDialogButtonBox* buttons = new QDialogButtonBox(this);
        m_run = buttons->addButton(tr_ui("Run"), QDialogButtonBox::AcceptRole);
        m_close = buttons->addButton(QDialogButtonBox::Close);
        m_close->setText(tr_ui("Close"));
        layout->addWidget(buttons);

        connect(refresh, &QPushButton::clicked, this, [this]{ fill_disks(); });
        connect(m_only_settings, &QCheckBox::toggled, this, [this](bool on){ m_disks->setEnabled(!on); });
        connect(m_run, &QPushButton::clicked, this, [this]{ run(); });
        connect(m_close, &QPushButton::clicked, this, [this]{ reject(); });
        connect(&m_timer, &QTimer::timeout, this, [this]{ look_for_card(); });
        fill_disks();
    }
    ~CardDialog() override{
        m_timer.stop();
        if (m_process != nullptr){
            m_process->disconnect();
        }
    }

protected:
    void reject() override{
        if (busy()){
            return;     //  the card is being written: not closed halfway
        }
        QDialog::reject();
    }

private:
    QLineEdit* add_field(QFormLayout* form, const QString& label, const QString& text){
        QLineEdit* field = new QLineEdit(text, this);
        form->addRow(label, field);
        return field;
    }
    bool busy() const{
        return m_process != nullptr || m_timer.isActive();
    }
    void set_busy(bool on){
        m_busy->setVisible(on);
        m_run->setEnabled(!on);
        m_close->setEnabled(!on);
    }
    void say(const QString& text, bool bad = false){
        m_status->setStyleSheet(bad ? "color: #ff7e72;" : "");
        m_status->setText(text);
    }
    void fill_disks(){
        m_disks->clear();
        QString error;
        m_disk_list = removable_disks(&error);
        for (const Disk& disk : m_disk_list){
            m_disks->addItem(QString("%1 (%2 GB)").arg(disk.name.isEmpty() ? disk.device : disk.name).arg(disk.gigabytes, 0, 'f', 1));
        }
        if (m_disk_list.empty()){
            m_disks->addItem(tr_ui("No SD card found: put one in and press Look again"));
        }
        if (!error.isEmpty()){
            say(error, true);
        }
    }
    Settings settings() const{
        Settings out;
        out.hostname = m_hostname->text().trimmed().toLower();
        out.user = m_user->text().trimmed();
        out.password = m_password->text();
        out.wifi_name = m_wifi->text();
        out.wifi_password = m_wifi_password->text();
        out.country = m_country->text().trimmed().toUpper();
        out.token = m_token.trimmed().isEmpty() ? new_token() : m_token.trimmed();
        return out;
    }

    void run(){
        m_settings = settings();
        const QString wrong = problem(m_settings);
        if (!wrong.isEmpty()){
            say(tr_ui(wrong), true);
            return;
        }
        if (m_only_settings->isChecked()){
            const QStringList cards = find_boot_partitions();
            if (cards.isEmpty()){
                say(tr_ui("No SD card with Raspberry Pi OS was found. Put it in and try again."), true);
                return;
            }
            const QString root = QDir::toNativeSeparators(cards.first());
            if (QMessageBox::question(this, windowTitle(), tr_ui("The settings of Claude GG are written to %1. Go on?").arg(root),
                    QMessageBox::Yes | QMessageBox::No, QMessageBox::No) != QMessageBox::Yes){
                return;
            }
            finish(cards.first());
            return;
        }

        const int index = m_disks->currentIndex();
        if (index < 0 || index >= (int)m_disk_list.size()){
            say(tr_ui("No SD card found: put one in and press Look again"), true);
            return;
        }
        const QString imager = imager_path();
        if (imager.isEmpty()){
            say(tr_ui("Raspberry Pi Imager is not installed. Its page is opened: install it, then press Run again."), true);
            QDesktopServices::openUrl(QUrl(IMAGER_PAGE));
            return;
        }
        const Disk disk = m_disk_list[index];
        const QString what = QString("%1 (%2 GB)").arg(disk.name.isEmpty() ? disk.device : disk.name).arg(disk.gigabytes, 0, 'f', 1);
        if (QMessageBox::warning(this, windowTitle(),
                tr_ui("Everything on %1 is erased. Go on?").arg(what), QMessageBox::Yes | QMessageBox::No, QMessageBox::No) != QMessageBox::Yes){
            return;
        }

        //  The boot partitions that are there before: the new card is one that is not one of them, or one without the settings of
        //  Claude GG.
        m_process = new QProcess(this);
        m_process->setProcessChannelMode(QProcess::MergedChannels);
#ifdef _WIN32
        //  Imager wants the rights of an administrator: Windows asks.
        auto quote = [](const QString& text){ return "'" + QString(text).replace("'", "''") + "'"; };
        const QString arguments = QString("--cli \"%1\" \"%2\"").arg(QString(IMAGE_URL), disk.device);
        m_process->start("powershell", {"-NoProfile", "-NonInteractive", "-Command",
            "$p = Start-Process -FilePath " + quote(imager) + " -ArgumentList " + quote(arguments) + " -Verb RunAs -Wait -PassThru; exit $p.ExitCode"});
#else
        const QString pkexec = QStandardPaths::findExecutable("pkexec");
        if (pkexec.isEmpty()){
            m_process->start(imager, {"--cli", QString(IMAGE_URL), disk.device});
        }else{
            m_process->start(pkexec, {imager, "--cli", QString(IMAGE_URL), disk.device});
        }
#endif
        connect(m_process, &QProcess::finished, this, [this](int code, QProcess::ExitStatus status){ written(code, status); });
        connect(m_process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error){
            if (error == QProcess::FailedToStart){
                written(-1, QProcess::CrashExit);
            }
        });
        set_busy(true);
        say(tr_ui("Raspberry Pi OS is downloaded and written to the card. This takes a few minutes: leave the card in."));
    }

    void written(int code, QProcess::ExitStatus status){
        if (m_process == nullptr){
            return;
        }
        const QString output = QString::fromLocal8Bit(m_process->readAll()).trimmed();
        m_process->deleteLater();
        m_process = nullptr;
        if (status != QProcess::NormalExit || code != 0){
            set_busy(false);
            say(tr_ui("Raspberry Pi Imager could not write the card.") + (output.isEmpty() ? QString() : "\n" + output.right(400)), true);
            return;
        }
        m_waited = 0;
        m_timer.start(1000);
        say(tr_ui("The card is written. Waiting for it to show up again: if it does not, take it out and put it back in."));
    }

    void look_for_card(){
        m_waited++;
        for (const QString& root : find_boot_partitions()){
            QFile user(QDir(root).filePath("user-data"));
            const bool ours = user.open(QIODevice::ReadOnly) && user.readAll().contains(MARK);
            if (!ours){
                m_timer.stop();
                finish(root);
                return;
            }
        }
        if (m_waited >= CARD_WAIT_SECONDS){
            m_timer.stop();
            set_busy(false);
            say(tr_ui("The card did not show up again. Take it out, put it back in, tick 'only add the settings' and press Run."), true);
        }
    }

    void finish(const QString& root){
        set_busy(false);
        QString error;
        if (!write_boot_partition(root, m_settings, error)){
            say(tr_ui("The settings could not be written to the card.") + "\n" + error, true);
            return;
        }
        m_token = m_settings.token;
        if (m_done){
            m_done(m_settings.hostname + ".local", m_settings.token);
        }
        say(tr_ui("The card is ready. Put it in the Raspberry Pi, plug in the phone and switch the Pi on. After about 10 to 15 minutes, test the connection. If it does not work, claudegg/install.log on the card says why."));
    }

    QString m_token;
    std::function<void(const QString&, const QString&)> m_done;
    Settings m_settings;
    QLineEdit* m_hostname = nullptr;
    QLineEdit* m_user = nullptr;
    QLineEdit* m_password = nullptr;
    QLineEdit* m_wifi = nullptr;
    QLineEdit* m_wifi_password = nullptr;
    QLineEdit* m_country = nullptr;
    QComboBox* m_disks = nullptr;
    QCheckBox* m_only_settings = nullptr;
    QProgressBar* m_busy = nullptr;
    QLabel* m_status = nullptr;
    QPushButton* m_run = nullptr;
    QPushButton* m_close = nullptr;
    std::vector<Disk> m_disk_list;
    QProcess* m_process = nullptr;
    QTimer m_timer;
    int m_waited = 0;
};

}


void open_dialog(QWidget* parent, const QString& token, const std::function<void(const QString& host, const QString& token)>& done){
    CardDialog dialog(parent, token, done);
    dialog.exec();
}


int run_checks(QStringList& report){
    int failures = 0;
    auto check = [&](bool ok, const QString& what){
        if (!ok){
            failures++;
            report << "FAILED: SD card: " + what;
        }
    };
    Settings good;
    good.password = "secret pass";
    good.wifi_name = "Home Wi-Fi";
    good.wifi_password = "wifi-password";
    good.token = "0123456789abcdef0123456789abcdef";
    check(problem(good).isEmpty(), "good settings are accepted (" + problem(good) + ")");
    {
        Settings bad = good;
        bad.hostname = "My Pi";
        check(!problem(bad).isEmpty(), "a name with a space is refused");
        bad = good;
        bad.user = "root";
        check(!problem(bad).isEmpty(), "root is refused");
        bad = good;
        bad.password = "two\nlines";
        check(!problem(bad).isEmpty(), "a password of two lines is refused");
        bad = good;
        bad.wifi_password = "short";
        check(!problem(bad).isEmpty(), "a Wi-Fi password under 8 characters is refused");
        bad = good;
        bad.country = "nld";
        check(!problem(bad).isEmpty(), "a country of three letters is refused");
        bad = good;
        bad.token = "abc";
        check(!problem(bad).isEmpty(), "a short token is refused");
        bad = good;
        bad.wifi_name.clear();
        bad.wifi_password.clear();
        check(problem(bad).isEmpty(), "no Wi-Fi (a cable) is fine");
    }
    const QString data = user_data(good);
    check(data.startsWith("#cloud-config\n") && data.contains("hostname: claudegg\n") && data.contains("  - name: claudegg\n")
          && data.contains("  - [bash, /boot/firmware/claudegg/firstboot.sh]\n"), "user-data names the Pi, the user and the first start");
    check(!data.contains(good.password) && !data.contains(good.wifi_password) && !data.contains(good.token), "user-data holds no password and no token");
    check(settings_file(good) == "secret pass\nHome Wi-Fi\nwifi-password\nNL\n0123456789abcdef0123456789abcdef\n", "the settings are one per line");
    const QString script = firstboot_script();
    check(script.startsWith("#!/bin/bash\n") && !script.contains('\r') && !script.contains('\t'), "the script is a bash script with Linux line ends");
    check(script.contains("rm -f \"$CARD/settings\"") && script.contains("install-agent.sh") && script.contains(".claudegg-agent/token"),
          "the script removes the settings, puts the token in place and runs the installer of the agent");
    check(!script.contains("eval") && !script.contains("source "), "the script never runs what is in the settings");
    check(new_token().size() == 32 && new_token() != new_token(), "a new token is 32 hex digits, and new each time");

    //  A made-up boot partition.
    const QString folder = QDir::temp().filePath("claudegg-picard-" + random_hex(4));
    QDir().mkpath(folder);
    QString error;
    check(!write_boot_partition(folder, good, error), "a folder that is no boot partition is not written to");
    error.clear();
    check(write_file(folder + "/cmdline.txt", "console=tty1\n", error) && write_file(folder + "/config.txt", "", error), "a made-up card (" + error + ")");
    check(write_boot_partition(folder, good, error), "the boot partition is written (" + error + ")");
    for (const char* name : {"user-data", "meta-data", "claudegg/firstboot.sh", "claudegg/settings"}){
        check(QFileInfo::exists(folder + "/" + name), QString("it has ") + name);
    }
    QFile meta(folder + "/meta-data");
    check(meta.open(QIODevice::ReadOnly) && meta.readAll().startsWith("instance-id: claudegg-"), "meta-data gives the card a new instance-id");
    meta.close();
    QDir(folder).removeRecursively();
    return failures;
}


}
}
}
