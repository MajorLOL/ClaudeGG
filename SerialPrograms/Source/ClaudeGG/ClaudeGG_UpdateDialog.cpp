/*  ClaudeGG Update Window
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include "Common/Compiler.h"
#include <QButtonGroup>
#include <QCheckBox>
#include <QCoreApplication>
#include <QDateTime>
#include <QDesktopServices>
#include <QDialog>
#include <QDir>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QLabel>
#include <QMessageBox>
#include <QPointer>
#include <QProcess>
#include <QProgressBar>
#include <QPushButton>
#include <QRadioButton>
#include <QScrollArea>
#include <QSettings>
#include <QTimer>
#include <QUrl>
#include <QVBoxLayout>
#include "Common/Cpp/Color.h"
#include "CommonFramework/Logging/Logger.h"
#include "Assistant/Assistant_Http.h"
#include "ClaudeGG_Instances.h"
#include "ClaudeGG_Language.h"
#include "ClaudeGG_Theme.h"
#include "ClaudeGG_Updater.h"
#include "ClaudeGG_UpdateDialog.h"

namespace PokemonAutomation{
namespace ClaudeGG{

using namespace Assistant;


namespace{

QSettings update_settings(){
    return QSettings(QSettings::IniFormat, QSettings::UserScope, "ClaudeGG", "Updates");
}

QString with_slash(QString path){
    path.replace('\\', '/');
    if (!path.isEmpty() && !path.endsWith('/')){
        path += '/';
    }
    return path;
}

QString megabytes(qint64 bytes){
    return QString::number((double)bytes / (1024.0 * 1024.0), 'f', bytes < 10 * 1024 * 1024 ? 1 : 0);
}

QLabel* paragraph(QWidget& parent, const QString& html){
    QLabel* label = new QLabel(html, &parent);
    label->setTextFormat(Qt::RichText);
    label->setWordWrap(true);
    label->setTextInteractionFlags(Qt::TextBrowserInteraction);
    label->setOpenExternalLinks(true);
    return label;
}

//  The other installations of this folder that run now (not this one).
QStringList other_running_installations(){
    QStringList running;
    InstanceRegistry registry(shared_base_path());
    const qint64 now = QDateTime::currentMSecsSinceEpoch();
    for (const InstanceInfo& info : registry.list(now, false)){
        if (info.running && info.id.toStdString() != current_instance()){
            running.push_back(info.name.isEmpty() ? tr_ui("Installation %1").arg(info.id) : info.name);
        }
    }
    return running;
}

//  What a window or a check at the start keeps: the connection, and what
//  uses it (gone first).
class DownloadHolder : public QObject{
public:
    using QObject::QObject;
    ~DownloadHolder(){
        download.reset();
        check.reset();
        transport.reset();
    }
    std::unique_ptr<HttpTransport> transport;
    std::unique_ptr<UpdateDownload> download;
    std::unique_ptr<UpdateCheck> check;
};

void log_line(const std::string& text, Color color = COLOR_BLUE){
    global_logger_tagged().log("Updates: " + text, color);
}

}


bool update_check_at_start(){
    return update_settings().value("check_at_start", true).toBool();
}
void set_update_check_at_start(bool on){
    QSettings settings = update_settings();
    settings.setValue("check_at_start", on);
}
QString skipped_update(){
    return update_settings().value("skipped", QString()).toString();
}
void set_skipped_update(const QString& build){
    QSettings settings = update_settings();
    settings.setValue("skipped", build);
}


UpdateTarget this_program(){
    UpdateTarget target;
    target.program = with_slash(QCoreApplication::applicationDirPath());
    target.data = with_slash(QString::fromStdString(shared_base_path()));
    if (!is_main_instance()){
        target.restart = instance_arguments(QString::fromStdString(current_instance()));
    }
    return target;
}


std::unique_ptr<QDialog> make_update_dialog(
    QWidget* parent, const UpdateResult& result, const UpdateTarget& target,
    HttpTransport* transport, bool at_start
){
    const ThemeColors& theme = theme_colors();
    const QColor link_color = theme.dark ? theme.accent : QColor(0x0b, 0x5c, 0xc4);
    const QString latest = version_text(result.latest.build);

    std::unique_ptr<QDialog> owner = std::make_unique<QDialog>(parent);
    QDialog& dialog = *owner;
    dialog.setObjectName("ppUpdateWindow");
    dialog.setWindowTitle(tr_ui("Update Claude GG"));
    dialog.setMinimumWidth(600);

    //  The connection and the download live as long as the window. The first
    //  child of the window: it goes before the widgets that it shows its
    //  progress in.
    DownloadHolder* holder = new DownloadHolder(&dialog);
    if (transport == nullptr){
        holder->transport = make_network_transport();
        transport = holder->transport.get();
    }
    holder->download = std::make_unique<UpdateDownload>(*transport);
    UpdateDownload* download = holder->download.get();

    QVBoxLayout* layout = new QVBoxLayout(&dialog);
    layout->setContentsMargins(26, 22, 26, 18);
    layout->setSpacing(12);

    QLabel* title = new QLabel(tr_ui("Build %1 is out").arg(latest), &dialog);
    title->setObjectName("ppUpdateTitle");
    title->setFont(display_font(34));
    layout->addWidget(title);

    QString facts = result.current > 0
        ? tr_ui("You have build %1.").arg(version_text(result.current))
        : tr_ui("You have a build without a number (a local build).");
    if (!result.latest.date.isEmpty()){
        facts += " " + tr_ui("Build %1 was published on %2.").arg(latest, result.latest.date);
    }
    if (result.latest.package_size > 0){
        facts += " " + tr_ui("The download is %1 MB.").arg(megabytes(result.latest.package_size));
    }
    facts = facts.toHtmlEscaped() + " <a href=\"" + result.page_url + "\" style=\"color: " + link_color.name() + "\">" +
        tr_ui("Open its page").toHtmlEscaped() + "</a>";
    layout->addWidget(paragraph(dialog, facts));

    //  What is new.
    QLabel* news_heading = new QLabel(tr_ui("What's new"), &dialog);
    news_heading->setObjectName("ppSectionTitle");
    QFont heading_font = news_heading->font();
    heading_font.setBold(true);
    news_heading->setFont(heading_font);
    layout->addWidget(news_heading);
    QScrollArea* news_area = new QScrollArea(&dialog);
    news_area->setWidgetResizable(true);
    news_area->setFrameShape(QFrame::NoFrame);
    news_area->setMinimumHeight(150);
    news_area->setMaximumHeight(300);
    QLabel* news = paragraph(dialog, result.news.empty()
        ? tr_ui("The release says nothing about what changed.").toHtmlEscaped()
        : news_html(result)
    );
    news->setObjectName("ppUpdateNews");
    news->setAlignment(Qt::AlignTop | Qt::AlignLeft);
    news_area->setWidget(news);
    layout->addWidget(news_area, 1);

    //  How.
    const bool installable = can_install(result);
    const QString beside_folder = side_by_side_folder(target.program, result.latest.build);
    QRadioButton* replace = new QRadioButton(tr_ui("Update this copy"), &dialog);
    replace->setObjectName("ppUpdateReplace");
    QLabel* replace_text = paragraph(dialog, tr_ui(
        "Claude GG closes, the new files take the place of the old ones, and it starts again. "
        "Your settings, installations, languages, pictures and logs stay as they are. "
        "If anything cannot be replaced, everything is put back as it was."
    ).toHtmlEscaped());
    replace_text->setObjectName("ppMuted");
    replace_text->setIndent(24);
    QRadioButton* beside = new QRadioButton(tr_ui("Install it next to this copy"), &dialog);
    beside->setObjectName("ppUpdateBeside");
    QLabel* beside_text = paragraph(dialog, tr_ui(
        "The new build goes into a folder of its own, %1, with a copy of your settings. "
        "This copy stays as it is, so you can use both and compare."
    ).arg(QDir::toNativeSeparators(QDir::cleanPath(beside_folder))).toHtmlEscaped());
    beside_text->setObjectName("ppMuted");
    beside_text->setIndent(24);
    QButtonGroup* how = new QButtonGroup(&dialog);
    how->addButton(replace);
    how->addButton(beside);
    replace->setChecked(true);
    layout->addWidget(replace);
    layout->addWidget(replace_text);
    layout->addWidget(beside);
    layout->addWidget(beside_text);

    QLabel* running = paragraph(dialog, QString());
    running->setObjectName("ppUpdateRunning");
    layout->addWidget(running);
    auto show_running = [running, replace]{
        const QStringList others = replace->isChecked() && !is_test_run() ? other_running_installations() : QStringList();
        running->setVisible(!others.isEmpty());
        running->setText(tr_ui("These run now and are closed for the update: %1.").arg(others.join(", ")).toHtmlEscaped());
    };
    show_running();
    QObject::connect(replace, &QRadioButton::toggled, running, show_running);

    QProgressBar* progress = new QProgressBar(&dialog);
    progress->setObjectName("ppUpdateProgress");
    progress->setTextVisible(false);
    progress->setRange(0, 1000);
    progress->setValue(0);
    progress->hide();
    layout->addWidget(progress);
    QLabel* status = paragraph(dialog, QString());
    status->setObjectName("ppUpdateStatus");
    layout->addWidget(status);
    if (!installable){
        status->setText((result.state != UpdateState::NEWER_AVAILABLE
            ? tr_ui("There is nothing newer to install.")
#ifdef _WIN32
            : tr_ui("This release does not list the SHA-256 of its package, so Claude GG does not install it itself. Download it from its page.")
#else
            : tr_ui("Claude GG installs updates itself on Windows only. Download this one from its page.")
#endif
        ).toHtmlEscaped());
    }

    QCheckBox* at_start_box = new QCheckBox(tr_ui("Check for updates when Claude GG starts"), &dialog);
    at_start_box->setObjectName("ppUpdateAtStart");
    at_start_box->setChecked(update_check_at_start());
    QObject::connect(at_start_box, &QCheckBox::toggled, [](bool on){
        set_update_check_at_start(on);
    });
    layout->addWidget(at_start_box);

    QHBoxLayout* buttons = new QHBoxLayout();
    buttons->setSpacing(10);
    layout->addLayout(buttons);
    QPushButton* skip = nullptr;
    if (at_start){
        skip = new QPushButton(tr_ui("Skip this build"), &dialog);
        skip->setObjectName("ppUpdateSkip");
        buttons->addWidget(skip);
        QObject::connect(skip, &QPushButton::clicked, &dialog, [&dialog, latest]{
            set_skipped_update(latest);
            dialog.reject();
        });
    }
    buttons->addStretch(1);
    QPushButton* later = new QPushButton(tr_ui("Later"), &dialog);
    later->setObjectName("ppUpdateLater");
    buttons->addWidget(later);
    QObject::connect(later, &QPushButton::clicked, &dialog, &QDialog::reject);
    QPushButton* start_new = new QPushButton(tr_ui("Start the new build"), &dialog);
    start_new->setObjectName("ppUpdateStartNew");
    start_new->hide();
    buttons->addWidget(start_new);
    QPushButton* install = new QPushButton(tr_ui("Install build %1").arg(latest), &dialog);
    install->setObjectName("ppUpdateInstall");
    install->setDefault(true);
    install->setEnabled(installable);
    buttons->addWidget(install);

    QDialog* dialog_pointer = &dialog;
    QObject::connect(install, &QPushButton::clicked, &dialog, [=]{
        if (download->running()){
            return;
        }
        const bool in_place = replace->isChecked();
        install->setEnabled(false);
        replace->setEnabled(false);
        beside->setEnabled(false);
        if (skip != nullptr){
            skip->setEnabled(false);
        }
        progress->show();
        progress->setValue(0);
        log_line("downloading build " + latest.toStdString() + (in_place ? " to update this copy." : " to install it next to this copy."));

        const QString folder = updates_folder(target.data) + latest + "/";
        download->start(
            result.package_url, result.latest.package_sha256, result.latest.package_size, folder,
            [=](UpdateDownload::Stage stage, qint64 done, qint64 total){
                switch (stage){
                case UpdateDownload::Stage::DOWNLOADING:
                    if (total > 0){
                        progress->setRange(0, 1000);
                        progress->setValue((int)std::min<qint64>(1000, done * 1000 / total));
                        status->setText(tr_ui("Downloading: %1 of %2 MB").arg(megabytes(done), megabytes(total)));
                    }else{
                        progress->setRange(0, 0);
                        status->setText(tr_ui("Downloading: %1 MB").arg(megabytes(done)));
                    }
                    break;
                case UpdateDownload::Stage::CHECKING:
                    status->setText(tr_ui("Checking the SHA-256 of the download..."));
                    break;
                case UpdateDownload::Stage::UNPACKING:
                    progress->setRange(0, 0);
                    status->setText(tr_ui("Unpacking..."));
                    break;
                default:
                    progress->setRange(0, 1000);
                    progress->setValue(1000);
                    break;
                }
            },
            [=](bool ok, const QString& error, const QString& package){
                if (!ok){
                    log_line("the download of build " + latest.toStdString() + " failed: " + error.toStdString(), COLOR_RED);
                    progress->hide();
                    status->setText(tr_ui("Not installed: %1").arg(error).toHtmlEscaped());
                    install->setEnabled(true);
                    replace->setEnabled(true);
                    beside->setEnabled(true);
                    if (skip != nullptr){
                        skip->setEnabled(true);
                    }
                    return;
                }
                log_line("build " + latest.toStdString() + " is downloaded, checked and unpacked in " + package.toStdString());

                if (!in_place){
                    QString why;
                    if (!install_side_by_side(package, beside_folder, target.data, why)){
                        log_line("installing next to this copy failed: " + why.toStdString(), COLOR_RED);
                        status->setText(tr_ui("Not installed: %1").arg(why).toHtmlEscaped());
                        install->setEnabled(true);
                        replace->setEnabled(true);
                        beside->setEnabled(true);
                        return;
                    }
                    QDir(folder).removeRecursively();
                    log_line("build " + latest.toStdString() + " is installed in " + beside_folder.toStdString());
                    status->setText(tr_ui("Build %1 is installed in %2. This copy stays as it is.")
                        .arg(latest, QDir::toNativeSeparators(QDir::cleanPath(beside_folder))).toHtmlEscaped());
                    later->setText(tr_ui("Close"));
                    start_new->show();
                    QObject::connect(start_new, &QPushButton::clicked, dialog_pointer, [=]{
                        if (!target.dry_run){
                            QProcess::startDetached(beside_folder + PROGRAM_FILE_NAME, QStringList(), beside_folder);
                        }
                        dialog_pointer->accept();
                    });
                    return;
                }

                if (target.dry_run){
                    status->setText(tr_ui("Ready: Claude GG closes now and starts again as build %1.").arg(latest).toHtmlEscaped());
                    return;
                }
                QString why;
                if (!start_apply_update(package, target.program, target.data, result.latest.build, target.restart, why)){
                    log_line("the update could not be started: " + why.toStdString(), COLOR_RED);
                    status->setText(tr_ui("Not installed: %1").arg(why).toHtmlEscaped());
                    install->setEnabled(true);
                    replace->setEnabled(true);
                    beside->setEnabled(true);
                    return;
                }
                status->setText(tr_ui("Ready: Claude GG closes now and starts again as build %1.").arg(latest).toHtmlEscaped());
                log_line("closing for the update to build " + latest.toStdString());
                //  The other installations of this folder and the overview use
                //  the same files: they close too.
                InstanceRegistry registry(shared_base_path());
                for (const InstanceInfo& info : registry.list(QDateTime::currentMSecsSinceEpoch(), false)){
                    if (info.running && info.id.toStdString() != current_instance()){
                        close_instance(info.id);
                    }
                }
                close_instances_overview();
                QTimer::singleShot(800, dialog_pointer, [dialog_pointer]{
                    dialog_pointer->close();
                    close_instance_windows();
                });
            }
        );
    });

    return owner;
}


void show_update_dialog(QWidget* parent, const UpdateResult& result, bool at_start){
    std::unique_ptr<QDialog> dialog = make_update_dialog(parent, result, this_program(), nullptr, at_start);
    QDialog* raw = dialog.release();
    raw->setAttribute(Qt::WA_DeleteOnClose, true);
    raw->show();
    raw->raise();
    raw->activateWindow();
}


void start_update_check_at_start(QWidget* window, const QString& project_url, const QString& build){
    if (window == nullptr || is_test_run() || !is_main_instance()){
        return;
    }
    const QString data = with_slash(QString::fromStdString(shared_base_path()));

    //  How the last update went.
    bool ok = false;
    QString updated_build;
    QString message;
    if (take_update_outcome(data, ok, updated_build, message)){
        clean_old_updates(data);
        QPointer<QWidget> pointer(window);
        QTimer::singleShot(1500, window, [pointer, ok, updated_build, message]{
            if (pointer == nullptr){
                return;
            }
            if (ok){
                log_line("this is build " + updated_build.toStdString() + " now: the update worked.");
                QMessageBox::information(pointer, tr_ui("Update Claude GG"), tr_ui("Claude GG is updated to build %1.").arg(updated_build));
            }else{
                log_line("the update to build " + updated_build.toStdString() + " failed: " + message.toStdString(), COLOR_RED);
                QMessageBox::warning(pointer, tr_ui("Update Claude GG"), message);
            }
        });
    }

    if (!update_check_at_start()){
        return;
    }
    const int current = build_of_this_program(build);
    if (current == 0){
        return;     //  A local build or one of a pull request: nothing to compare.
    }

    //  A while after the window is up, so that the start is not slower.
    QPointer<QWidget> pointer(window);
    QTimer::singleShot(5000, window, [pointer, project_url, build]{
        if (pointer == nullptr){
            return;
        }
        DownloadHolder* holder = new DownloadHolder(pointer);
        holder->transport = make_network_transport();
        holder->check = std::make_unique<UpdateCheck>(*holder->transport, project_url, build);
        QPointer<QObject> holder_pointer(holder);
        holder->check->start([pointer, holder_pointer](const UpdateResult& result){
            //  Not here: this runs inside the connection.
            if (holder_pointer != nullptr){
                holder_pointer->deleteLater();
            }
            if (result.state == UpdateState::FAILED){
                log_line("the check at the start failed: " + result.error.toStdString());
                return;
            }
            if (result.state != UpdateState::NEWER_AVAILABLE){
                log_line("the check at the start found nothing newer.");
                return;
            }
            const QString latest = version_text(result.latest.build);
            log_line("build " + latest.toStdString() + " is out.");
            if (latest == skipped_update()){
                log_line("build " + latest.toStdString() + " was skipped: not offered.");
                return;
            }
            if (pointer != nullptr){
                //  The window has a connection of its own.
                show_update_dialog(pointer, result, true);
            }
        });
    });
}



}
}
