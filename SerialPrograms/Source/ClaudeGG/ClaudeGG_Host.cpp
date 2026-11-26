/*  Claude GG Main Window (the host)
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <cstdlib>
#include <functional>
#include <map>
#include <memory>
#include <QApplication>
#include <QCloseEvent>
#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QEvent>
#include <QEventLoop>
#include <QFile>
#include <QImage>
#include <QPalette>
#include <QPointer>
#include <QProcess>
#include <QResizeEvent>
#include <QScreen>
#include <QTextStream>
#include <QTimer>
#include <QWidget>
#include "Common/Cpp/Color.h"
#include "Common/Cpp/Logging/AbstractLogger.h"
#include "Common/Cpp/Logging/GlobalLogger.h"
#include "CommonFramework/Environment/HardwareValidation.h"
#include "CommonFramework/Logging/Logger.h"
#include "ClaudeGG_Embed.h"
#include "ClaudeGG_Host.h"
#include "ClaudeGG_InstancePaths.h"
#include "ClaudeGG_Instances.h"
#include "ClaudeGG_Logo.h"
#include "ClaudeGG_Setup.h"

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <Windows.h>
#endif

namespace PokemonAutomation{
namespace ClaudeGG{


const char* const HOST_OPTION = "--host";
const char* const STANDALONE_OPTION = "--standalone";
const char* const HOST_TEST_OPTION = "--host-test";


namespace{

bool g_host = false;

}

void read_host_options(int argc, char* argv[]){
    bool host = false;
    bool standalone = false;
    int others = 0;
    for (int c = 1; c < argc; c++){
        const std::string argument = argv[c];
        if (argument == HOST_OPTION){
            host = true;
        }else if (argument == STANDALONE_OPTION){
            standalone = true;
        }else{
            others++;
        }
    }
#ifdef _WIN32
    g_host = !standalone && (host || others == 0);
#else
    //  A window of another process can only be a child of a window on Windows.
    (void)host;
    (void)standalone;
    (void)others;
    g_host = false;
#endif
}

bool is_host(){
    return g_host;
}


namespace{

void wait_for(int msec){
    QEventLoop loop;
    QTimer::singleShot(msec, &loop, &QEventLoop::quit);
    loop.exec();
}

QPalette dark_palette(){
    QPalette palette;
    palette.setColor(QPalette::Window, QColor(8, 8, 10));
    return palette;
}


//  ---------------------------------------------------------------------
//  The window
//  ---------------------------------------------------------------------

class HostWindow : public QWidget{
public:
    HostWindow(std::shared_ptr<InstanceRegistry> registry, bool test)
        : QWidget(nullptr, Qt::Window)
        , m_registry(std::move(registry))
        , m_test(test)
    {
        setWindowTitle("Claude GG");
        setWindowIcon(app_icon());
        setAutoFillBackground(true);
        setPalette(dark_palette());
        resize(1280, 800);

        m_arguments = [](const QString& installation, quintptr place){
            return QStringList{
                INSTANCE_OPTION, installation,
                EMBED_IN_OPTION, QString::number((qulonglong)place),
            };
        };

        SetupRequest request;
        request.overview = true;
        request.host = true;
        request.instance_list = [this]{
            return m_registry->list(QDateTime::currentMSecsSinceEpoch(), true);
        };
        request.instance_open = [this](const QString& id){
            open(id);
        };
        request.instance_create = [this]() -> QString{
            const QString id = m_registry->create(QDateTime::currentMSecsSinceEpoch());
            if (id.isEmpty()){
                global_logger_tagged().log("Installations: a new installation could not be made.", COLOR_RED);
                return QString();
            }
            open(id);
            return id;
        };
        request.instance_remove = [this](const QString& id){
            return m_registry->remove(id, QDateTime::currentMSecsSinceEpoch());
        };
        request.instance_rename = [this](const QString& id, const QString& name){
            return m_registry->rename(id, name);
        };
        request.instance_close = [this](const QString& id){
            close_installation(id);
        };
        m_view = make_overview_view(this, request);
        m_view->widget()->setGeometry(rect());
        m_view->widget()->show();

        m_timer.setInterval(200);
        connect(&m_timer, &QTimer::timeout, this, [this]{
            poll();
        });
        m_timer.start();
    }

    virtual ~HostWindow() override{
        //  Nothing that it started runs on without it.
        for (auto& entry : m_embedded){
            if (entry.second.process != nullptr && entry.second.process->state() != QProcess::NotRunning){
                entry.second.process->kill();
                entry.second.process->waitForFinished(3000);
            }
        }
    }

    //  What an installation is started with (the test starts other things).
    void set_arguments(std::function<QStringList(const QString& id, quintptr container)> arguments){
        m_arguments = std::move(arguments);
    }
    //  More of the same, after the ones that there are.
    void set_extra_arguments(const QStringList& extra){
        const auto before = m_arguments;
        m_arguments = [before, extra](const QString& installation, quintptr place){
            return before(installation, place) + extra;
        };
    }

    AppView* view() const{
        return m_view;
    }
    //  The installation that is shown (empty: the overview).
    const QString& current() const{
        return m_current;
    }
    bool has(const QString& id) const{
        return m_embedded.find(id) != m_embedded.end();
    }
    bool running(const QString& id) const{
        const auto it = m_embedded.find(id);
        return it != m_embedded.end() && it->second.process != nullptr && it->second.process->state() != QProcess::NotRunning;
    }
    qint64 process_id(const QString& id) const{
        const auto it = m_embedded.find(id);
        return it == m_embedded.end() || it->second.process == nullptr ? 0 : (qint64)it->second.process->processId();
    }
    quintptr container(const QString& id) const{
        const auto it = m_embedded.find(id);
        return it == m_embedded.end() || it->second.container.isNull() ? 0 : (quintptr)it->second.container->winId();
    }

    //  An installation was pressed (or made): it is shown in this window, and
    //  started first when it does not run.
    void open(const QString& id){
        if (!valid_instance_id(id)){
            return;
        }
        if (running(id)){
            m_embedded[id].waiting = false;
            show_installation(id);
            return;
        }
        //  One that was started before this window was keeps the windows of its
        //  own: it comes forward there.
        if (send_instance_command(instance_link_name(shared_base_path(), "i" + id), "show")){
            return;
        }
        start(id);
    }

    //  The overview is shown, the installations are hidden (they run on).
    void show_overview(){
        for (auto& entry : m_embedded){
            entry.second.waiting = false;
            if (!entry.second.container.isNull()){
                entry.second.container->hide();
            }
        }
        m_current.clear();
        if (isMinimized()){
            showNormal();
        }
        raise();
        activateWindow();
        m_view->widget()->setFocus();
    }

    //  "Close" on an installation of this window: it is asked to close its
    //  windows, as its user would, and ended when it does not (the setup, that
    //  only skips what is in front of it).
    void close_installation(const QString& id){
        if (!close_instance(id)){
            global_logger_tagged().log("Installations: installation " + id.toStdString() + " did not answer a request to close.", COLOR_RED);
        }
        auto it = m_embedded.find(id);
        if (it != m_embedded.end()){
            it->second.closing.start();
        }
    }

    //  Every installation of this window is closed, then the ones that do not
    //  end are ended.
    void close_all(int wait_msec){
        for (auto& entry : m_embedded){
            if (running(entry.first)){
                close_instance(entry.first);
            }
        }
        QElapsedTimer time;
        time.start();
        while (time.elapsed() < wait_msec){
            bool any = false;
            for (const auto& entry : m_embedded){
                any = any || running(entry.first);
            }
            if (!any){
                break;
            }
            wait_for(100);
        }
        for (auto& entry : m_embedded){
            if (running(entry.first)){
                global_logger_tagged().log("Installations: installation " + entry.first.toStdString() + " did not close: it is ended.", COLOR_RED);
                entry.second.process->kill();
                entry.second.process->waitForFinished(3000);
            }
        }
    }

protected:
    virtual void resizeEvent(QResizeEvent* event) override{
        QWidget::resizeEvent(event);
        place_children();
    }
    virtual void changeEvent(QEvent* event) override{
        QWidget::changeEvent(event);
        //  Back in this window (from another program): what is typed goes on to
        //  the installation that is shown, as it did before.
        if (event->type() == QEvent::ActivationChange && isActiveWindow() && !m_current.isEmpty()){
            const QString id = m_current;
            QTimer::singleShot(0, this, [this, id]{
                auto it = m_embedded.find(id);
                if (m_current == id && it != m_embedded.end() && !it->second.container.isNull() && it->second.process != nullptr){
                    focus_child_window((quintptr)it->second.container->winId(), (qint64)it->second.process->processId());
                }
            });
        }
    }
    virtual void closeEvent(QCloseEvent* event) override{
        //  The installations are in this window: they go with it, and what is
        //  open in them is saved the way it is when their window is closed.
        hide();
        close_all(8000);
        event->accept();
        if (!m_test){
            QMetaObject::invokeMethod(QCoreApplication::instance(), []{
                QCoreApplication::quit();
            }, Qt::QueuedConnection);
        }
    }

private:
    struct Embedded{
        QPointer<QWidget> container;
        std::unique_ptr<QProcess> process;
        //  It was asked for and its window is not there yet: it is shown when it is.
        bool waiting = true;
        QElapsedTimer age;
        //  Asked to close: ended when it takes too long.
        QElapsedTimer closing;
    };

    void place_children(){
        if (m_view != nullptr){
            m_view->widget()->setGeometry(rect());
        }
        for (auto& entry : m_embedded){
            if (!entry.second.container.isNull()){
                entry.second.container->setGeometry(rect());
            }
        }
    }

    void start(const QString& id){
        drop(id);
        Embedded& embedded = m_embedded[id];
        QWidget* place = new QWidget(this);
        place->setAttribute(Qt::WA_NativeWindow, true);
        place->setAutoFillBackground(true);
        place->setPalette(dark_palette());
        place->setGeometry(rect());
        place->hide();
        const quintptr handle = (quintptr)place->winId();
        embedded.container = place;
        embedded.process = std::make_unique<QProcess>();
        QProcess& process = *embedded.process;
        process.setProgram(QCoreApplication::applicationFilePath());
        process.setArguments(m_arguments(id, handle));
        process.setWorkingDirectory(QString::fromStdString(shared_base_path()));
        //  Nobody reads what it prints (it has its own log).
        process.setStandardOutputFile(QProcess::nullDevice());
        process.setStandardErrorFile(QProcess::nullDevice());
        embedded.waiting = true;
        embedded.age.start();
        process.start();
        global_logger_tagged().log("Installations: installation " + id.toStdString() + " starts in the main window.", COLOR_BLUE);
    }

    void drop(const QString& id){
        auto it = m_embedded.find(id);
        if (it == m_embedded.end()){
            return;
        }
        if (!it->second.container.isNull()){
            it->second.container->hide();
            it->second.container->deleteLater();
        }
        if (it->second.process != nullptr && it->second.process->state() != QProcess::NotRunning){
            it->second.process->kill();
            it->second.process->waitForFinished(2000);
        }
        m_embedded.erase(it);
        if (m_current == id){
            m_current.clear();
        }
    }

    void show_installation(const QString& id){
        auto it = m_embedded.find(id);
        if (it == m_embedded.end() || it->second.container.isNull()){
            return;
        }
        for (auto& entry : m_embedded){
            if (entry.first != id && !entry.second.container.isNull()){
                entry.second.container->hide();
            }
        }
        QWidget* place = it->second.container;
        place->setGeometry(rect());
        place->show();
        place->raise();
        m_current = id;
        //  What is typed goes to it.
        focus_child_window((quintptr)place->winId(), (qint64)it->second.process->processId());
    }

    void poll(){
        QStringList ids;
        for (const auto& entry : m_embedded){
            ids << entry.first;
        }
        for (const QString& id : ids){
            auto it = m_embedded.find(id);
            if (it == m_embedded.end()){
                continue;
            }
            Embedded& embedded = it->second;
            if (embedded.process == nullptr || embedded.process->state() == QProcess::NotRunning){
                global_logger_tagged().log("Installations: installation " + id.toStdString() + " has ended.", COLOR_BLUE);
                const bool was_shown = m_current == id;
                drop(id);
                if (was_shown){
                    show_overview();
                }
                continue;
            }
            if (embedded.waiting){
                if (!embedded.container.isNull() &&
                    count_child_windows((quintptr)embedded.container->winId(), (qint64)embedded.process->processId()) > 0
                ){
                    embedded.waiting = false;
                    show_installation(id);
                }else if (embedded.age.elapsed() > 180000){
                    embedded.waiting = false;
                }
            }
            if (embedded.closing.isValid() && embedded.closing.elapsed() > 10000){
                global_logger_tagged().log("Installations: installation " + id.toStdString() + " did not close: it is ended.", COLOR_RED);
                embedded.closing.invalidate();
                embedded.process->kill();
            }
        }
    }

private:
    std::shared_ptr<InstanceRegistry> m_registry;
    bool m_test;
    AppView* m_view = nullptr;
    QTimer m_timer;
    std::function<QStringList(const QString& id, quintptr container)> m_arguments;
    std::map<QString, Embedded> m_embedded;
    QString m_current;
};

}


//  ---------------------------------------------------------------------
//  The program
//  ---------------------------------------------------------------------

int run_host(QApplication& application){
    const std::string scratch = shared_base_path();
    const auto registry = std::make_shared<InstanceRegistry>(scratch);

    //  There is one main window: a second start asks the first to come forward.
    const QString link_name = instance_link_name(scratch, "hub");
    InstanceGuard guard(QString::fromStdString(instances_root_path(scratch)), "hub.lock");
    if (!guard.acquired()){
        send_instance_command(link_name, "show");
        return 0;
    }

    //  Is this computer powerful enough? The installations that run in this window
    //  do not ask: a message of that check would be a window of its own.
    if (!check_hardware()){
        return 1;
    }

    HostWindow window(registry, false);
    InstanceLink link(link_name, [&window](const QString& command){
        if (command == "show"){
            window.show_overview();
        }
    });
    window.showMaximized();
    window.raise();
    window.activateWindow();
    //  The first installation is what the program has always opened: in this window.
    window.open(QString::fromStdString(MAIN_INSTANCE));
    return application.exec();
}


//  ---------------------------------------------------------------------
//  The test
//  ---------------------------------------------------------------------

namespace{

QImage grab_window(const QWidget& window){
    QScreen* screen = window.screen();
    if (screen == nullptr){
        return QImage();
    }
    const QPoint origin = window.mapToGlobal(QPoint(0, 0));
    return screen->grabWindow(0, origin.x(), origin.y(), window.width(), window.height()).toImage();
}

bool is_red(const QImage& picture, int x, int y){
    if (picture.isNull()){
        return false;
    }
    const QColor color = picture.pixelColor(std::min(x, picture.width() - 1), std::min(y, picture.height() - 1));
    return color.red() > 150 && color.green() < 90 && color.blue() < 90;
}

//  Is there anything to see in it (not one colour)?
bool has_content(const QImage& picture){
    if (picture.isNull()){
        return false;
    }
    int low = 255;
    int high = 0;
    for (int y = 0; y < picture.height(); y += 9){
        for (int x = 0; x < picture.width(); x += 9){
            const int value = picture.pixelColor(x, y).lightness();
            low = std::min(low, value);
            high = std::max(high, value);
        }
    }
    return high - low > 40;
}

}

int run_host_test(QApplication& application, const QString& folder){
    (void)application;
    Logger& logger = global_logger_tagged();
    QStringList report;
    int wrong = 0;
    auto check = [&](bool fine, const QString& what){
        report << (fine ? "ok:     " : "FAILED: ") + what;
        if (!fine){
            wrong++;
            logger.log("Host test: FAILED: " + what.toStdString(), COLOR_RED);
        }
    };
    auto note = [&](const QString& what){
        report << "        " + what;
    };
    auto finish = [&]() -> int{
        if (!folder.isEmpty()){
            QDir().mkpath(folder);
            QFile file(folder + "/host-test.txt");
            if (file.open(QIODevice::WriteOnly | QIODevice::Truncate)){
                QTextStream(&file) << report.join("\n") << "\n";
            }
        }
        logger.log(
            wrong == 0 ? "Host test: passed." : "Host test: " + std::to_string(wrong) + " failed.",
            wrong == 0 ? COLOR_BLUE : COLOR_RED
        );
        return wrong == 0 ? 0 : 1;
    };

#ifndef _WIN32
    report << "skipped: the main window is for Windows";
    return finish();
#else
    const std::string scratch = shared_base_path();
    const auto registry = std::make_shared<InstanceRegistry>(scratch);
    const QString hub_name = instance_link_name(scratch, "hub");
    const qint64 own_pid = (qint64)QCoreApplication::applicationPid();
    auto save = [&](const QImage& picture, const QString& name){
        if (!folder.isEmpty() && !picture.isNull()){
            QDir().mkpath(folder);
            picture.save(folder + "/" + name + ".jpg", "JPG", 80);
        }
    };
    //  Both sizes within a few pixels.
    auto fills = [](const QSize& child, const QSize& parent){
        return std::abs(child.width() - parent.width()) <= 3 && std::abs(child.height() - parent.height()) <= 3;
    };
    auto size_text = [](const QSize& child, const QSize& parent){
        return QString("%1x%2 in %3x%4").arg(child.width()).arg(child.height()).arg(parent.width()).arg(parent.height());
    };

    //  ---- A. An installation that is only a colour: what Windows says.
    {
        const QString id = "ci-host";
        registry->rename(id, "Host test");
        HostWindow window(registry, true);
        window.set_arguments([](const QString& installation, quintptr place){
            return QStringList{
                EMBED_PROBE_OPTION, INSTANCE_OPTION, installation,
                EMBED_IN_OPTION, QString::number((qulonglong)place),
            };
        });
        window.resize(900, 560);
        window.show();
        window.raise();
        window.activateWindow();
        InstanceLink link(hub_name, [&window](const QString& command){
            if (command == "show"){
                window.show_overview();
            }
        });
        check(link.listening(), "A: the main window listens for what the installations tell it");
        wait_for(2500);
        AppView* view = window.view();
        check(view->page() == "instances", "A: the main window starts on the overview");
        check(view->has_button("inst:" + id) && view->has_button("inst-new"), "A: it lists the installation and has a place to make a new one");
        check(count_top_level_windows(own_pid) == 1, "A: the program has one window on the taskbar (" + QString::number(count_top_level_windows(own_pid)) + ")");
        save(grab_window(window), "host-a1-overview");

        check(view->click("inst:" + id), "A: a click on the installation opens it");
        bool shown = false;
        for (int tries = 0; tries < 300 && !shown; tries++){
            wait_for(200);
            shown = window.current() == id;
        }
        check(shown, "A: it is shown in the window as soon as its window is there");
        const qint64 child = window.process_id(id);
        check(child != 0 && child != own_pid, "A: it is a process of its own");
        QSize child_size, parent_size;
        bool visible = false;
        bool child_style = false;
        wait_for(600);
        const bool described = describe_child_window(window.container(id), child, &child_size, &parent_size, &visible, &child_style);
        check(described && visible && child_style, "A: its window is a visible child window of the main window");
        check(described && fills(child_size, parent_size), "A: it fills the main window (" + size_text(child_size, parent_size) + ")");
        check(count_top_level_windows(child) == 0, "A: the installation has no window of its own on the taskbar (" + QString::number(count_top_level_windows(child)) + ")");
        check(count_top_level_windows(own_pid) == 1, "A: and the program still has one (" + QString::number(count_top_level_windows(own_pid)) + ")");
        QImage picture = grab_window(window);
        save(picture, "host-a2-installation");
        check(is_red(picture, picture.width() / 4, picture.height() / 4), "A: the installation is what is on the screen");

        //  The way back: what the button "Installations" of an installation does.
        check(send_instance_command(hub_name, "show"), "A: the main window answers the button 'Installations'");
        wait_for(600);
        picture = grab_window(window);
        save(picture, "host-a3-back");
        check(window.current().isEmpty(), "A: it shows the overview again");
        check(!is_red(picture, picture.width() / 4, picture.height() / 4), "A: and the overview is on the screen, not the installation");
        check(window.running(id), "A: the installation runs on");
        check(view->has_button("inst:" + id), "A: with its miniature");

        //  Again, and the window changes size.
        check(view->click("inst:" + id), "A: the installation is opened again");
        wait_for(800);
        check(window.current() == id, "A: it is shown again");
        window.resize(1000, 600);
        bool follows = false;
        for (int tries = 0; tries < 40 && !follows; tries++){
            wait_for(150);
            follows = describe_child_window(window.container(id), child, &child_size, &parent_size, &visible, &child_style) && fills(child_size, parent_size);
        }
        check(follows, "A: it follows the main window when that is made larger (" + size_text(child_size, parent_size) + ")");

        //  Close, from the overview: two presses.
        bool can_close = false;
        for (int tries = 0; tries < 40 && !can_close; tries++){
            wait_for(250);
            can_close = view->has_button("inst-close:" + id);
        }
        check(can_close, "A: the installation says that it runs, so it can be closed");
        view->click("inst-close:" + id);
        view->click("inst-close:" + id);
        bool gone = false;
        for (int tries = 0; tries < 100 && !gone; tries++){
            wait_for(200);
            gone = !window.has(id);
        }
        check(gone, "A: 'Close' ends the installation, and it is gone from the window");
        check(window.current().isEmpty(), "A: the overview is shown after it");

        //  Closing the main window closes what is in it.
        check(view->click("inst:" + id), "A: opened once more");
        shown = false;
        for (int tries = 0; tries < 300 && !shown; tries++){
            wait_for(200);
            shown = window.current() == id;
        }
        check(shown, "A: it is shown");
        const bool closed = window.close();
        check(closed && !window.running(id), "A: closing the main window ends the installation in it");
    }

    //  ---- B and C. The program itself as an installation.
    auto real = [&](const QString& id, const QStringList& extra, bool must_close, const QString& what){
        registry->rename(id, "Test " + what);
        HostWindow window(registry, true);
        window.set_extra_arguments(extra);
        window.resize(900, 560);
        window.show();
        window.raise();
        window.activateWindow();
        InstanceLink link(hub_name, [&window](const QString& command){
            if (command == "show"){
                window.show_overview();
            }
        });
        wait_for(2500);
        AppView* view = window.view();
        check(view->click("inst:" + id), what + ": a click on the installation starts it");
        bool shown = false;
        for (int tries = 0; tries < 600 && !shown; tries++){
            wait_for(250);
            shown = window.current() == id;
            if (!window.running(id) && !shown){
                break;
            }
        }
        check(shown, what + ": it is shown in the main window when its window is there");
        if (!shown){
            note(window.running(id) ? "the installation runs, and has made no window in the main window" : "the installation has ended");
            if (window.running(id)){
                note("its windows: " + describe_process_windows(window.process_id(id)));
                QScreen* screen = QGuiApplication::primaryScreen();
                if (screen != nullptr){
                    save(screen->grabWindow(0).toImage(), "host-" + what + "-screen");
                }
            }
            window.close();
            return;
        }
        const qint64 child = window.process_id(id);
        wait_for(4000);
        QSize child_size, parent_size;
        bool visible = false;
        bool child_style = false;
        const bool described = describe_child_window(window.container(id), child, &child_size, &parent_size, &visible, &child_style);
        check(described && visible && child_style, what + ": its window is a visible child window of the main window");
        check(described && fills(child_size, parent_size), what + ": it fills the main window (" + size_text(child_size, parent_size) + ")");
        check(count_top_level_windows(child) == 0, what + ": it has no window of its own on the taskbar (" + QString::number(count_top_level_windows(child)) + ")");
        check(count_top_level_windows(own_pid) == 1, what + ": the program has one window on the taskbar (" + QString::number(count_top_level_windows(own_pid)) + ")");
        const QImage picture = grab_window(window);
        save(picture, "host-" + what);
        check(has_content(picture), what + ": there is something to see in it");

        if (must_close){
            //  Close is a button of the overview: back to it, as a person goes.
            window.show_overview();
            wait_for(1500);
            bool can_close = false;
            for (int tries = 0; tries < 120 && !can_close; tries++){
                wait_for(250);
                can_close = view->has_button("inst-close:" + id);
            }
            check(can_close, what + ": it tells the overview that it runs");
            if (!can_close){
                //  What is in the folder of the installation, and what the list makes of it.
                const QString where = registry->folder(id);
                QFile status(where + "status.json");
                QString content = status.open(QIODevice::ReadOnly) ? QString::fromUtf8(status.readAll()).simplified() : QString("no status.json");
                const InstanceInfo info = registry->read(id, QDateTime::currentMSecsSinceEpoch(), false);
                note("its folder: " + QDir(where).entryList(QDir::Files).join(", ") + "; status.json: " + content +
                    "; the list says: " + (info.running ? "running" : "not running") + ", state '" + info.state + "'");
            }
            view->click("inst-close:" + id);
            view->click("inst-close:" + id);
            bool gone = false;
            for (int tries = 0; tries < 150 && !gone; tries++){
                wait_for(200);
                gone = !window.has(id);
            }
            check(gone, what + ": 'Close' ends it");
            if (!gone){
                note("its windows: " + describe_process_windows(child) + "; it runs: " + (window.running(id) ? "yes" : "no"));
            }
        }
        window.close();
        check(!window.running(id), what + ": closing the main window ends it");
    };
    real("ci-host-b", QStringList(), false, "setup");
    real("ci-host-c", QStringList{"--no-language-prompt"}, true, "main-window");

    return finish();
#endif
}


}
}
