/*  Claude GG Embedding
 *
 *  Part of Claude GG (ClaudeGG before), which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <cstdlib>
#include <atomic>
#include <chrono>
#include <cstring>
#include <memory>
#include <thread>
#include <vector>
#include <QApplication>
#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QEventLoop>
#include <QFile>
#include <QImage>
#include <QPainter>
#include <QPixmap>
#include <QPointer>
#include <QProcess>
#include <QScreen>
#include <QTextStream>
#include <QTimer>
#include <QWidget>
#include <QWindow>
#include "Common/Cpp/Color.h"
#include "Common/Cpp/Logging/AbstractLogger.h"
#include "Common/Cpp/Logging/GlobalLogger.h"
#include "CommonFramework/Logging/Logger.h"
#include "ClaudeGG_Embed.h"
#include "ClaudeGG_InstancePaths.h"
#include "ClaudeGG_Instances.h"

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <Windows.h>
#endif

namespace PokemonAutomation{
namespace ClaudeGG{


const char* const EMBED_IN_OPTION = "--embed-in";
const char* const EMBED_PROBE_OPTION = "--embed-probe";
const char* const EMBED_TEST_OPTION = "--embed-test";


namespace{

quintptr g_parent = 0;
QWindow* g_foreign = nullptr;
QTimer* g_fit_timer = nullptr;
std::vector<QPointer<QWidget>> g_windows;


#ifdef _WIN32

//  The size of the window we were given, in pixels of the screen.
bool parent_size(QSize& size){
    RECT rect;
    if (!GetClientRect((HWND)g_parent, &rect)){
        return false;
    }
    size = QSize(rect.right - rect.left, rect.bottom - rect.top);
    return true;
}

//  The windows of this process follow the size of the window they are in.
void fit_windows(){
    if (g_parent == 0 || !IsWindow((HWND)g_parent)){
        return;
    }
    QSize physical;
    if (!parent_size(physical) || physical.isEmpty()){
        return;
    }
    for (const QPointer<QWidget>& window : g_windows){
        if (window.isNull()){
            continue;
        }
        const qreal ratio = window->devicePixelRatioF();
        const QSize wanted(qRound(physical.width() / ratio), qRound(physical.height() / ratio));
        if (window->size() != wanted || window->pos() != QPoint(0, 0)){
            window->setGeometry(QRect(QPoint(0, 0), wanted));
        }
    }
}

struct ChildSearch{
    HWND parent = nullptr;
    DWORD pid = 0;
    std::vector<HWND> found;
};

BOOL CALLBACK collect_child(HWND window, LPARAM parameter){
    ChildSearch& search = *(ChildSearch*)parameter;
    DWORD pid = 0;
    GetWindowThreadProcessId(window, &pid);
    if (pid == search.pid && GetParent(window) == search.parent){
        search.found.push_back(window);
    }
    return TRUE;
}

//  The windows on the taskbar of a process.
struct TopSearch{
    DWORD pid = 0;
    int count = 0;
};
BOOL CALLBACK collect_top(HWND window, LPARAM parameter){
    TopSearch& search = *(TopSearch*)parameter;
    DWORD pid = 0;
    GetWindowThreadProcessId(window, &pid);
    if (pid != search.pid || !IsWindowVisible(window) || GetParent(window) != nullptr || GetWindow(window, GW_OWNER) != nullptr){
        return TRUE;
    }
    if ((GetWindowLongW(window, GWL_EXSTYLE) & WS_EX_TOOLWINDOW) != 0){
        return TRUE;
    }
    search.count++;
    return TRUE;
}

//  The window that this process was given goes (the main window was closed, or
//  ended): what is open here is closed as its window would be, and when that
//  does not end the process, it ends. A thread of its own, because the loop of
//  events may be what does not answer.
void start_guard(){
    static std::atomic<bool> started(false);
    if (started.exchange(true)){
        return;
    }
    const HWND parent = (HWND)g_parent;
    std::thread([parent]{
        while (IsWindow(parent)){
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }
        global_logger_tagged().log("Embedding: the window that this was given is gone: the windows are closed.");
        QCoreApplication* application = QCoreApplication::instance();
        if (application == nullptr){
            std::_Exit(0);
        }
        QMetaObject::invokeMethod(application, []{
            close_instance_windows();
        }, Qt::QueuedConnection);
        std::this_thread::sleep_for(std::chrono::milliseconds(2500));
        QMetaObject::invokeMethod(application, []{
            QCoreApplication::quit();
        }, Qt::QueuedConnection);
        std::this_thread::sleep_for(std::chrono::milliseconds(8000));
        global_logger_tagged().log("Embedding: the process did not end: it ends now.", COLOR_RED);
        std::_Exit(0);
    }).detach();
}

#endif

}


void read_embed_options(int argc, char* argv[]){
    for (int c = 1; c + 1 < argc; c++){
        if (std::strcmp(argv[c], EMBED_IN_OPTION) == 0){
            bool fine = false;
            const qulonglong value = QString::fromUtf8(argv[c + 1]).toULongLong(&fine);
            if (fine){
                g_parent = (quintptr)value;
            }
        }
    }
}

bool is_embedded(){
    return g_parent != 0;
}
quintptr embed_parent(){
    return g_parent;
}

bool embed_instance_window(QWidget* window){
#ifdef _WIN32
    if (g_parent == 0 || window == nullptr || !IsWindow((HWND)g_parent)){
        return false;
    }
    if (g_foreign == nullptr){
        g_foreign = QWindow::fromWinId((WId)g_parent);
    }
    if (g_foreign == nullptr){
        return false;
    }
    //  No frame; a window that is a child has none either way. The native
    //  window is made now, so that it can be given its parent before it is shown.
    window->setWindowFlags(Qt::Window | Qt::FramelessWindowHint);
    window->setAttribute(Qt::WA_NativeWindow, true);
    window->winId();
    QWindow* handle = window->windowHandle();
    if (handle == nullptr){
        return false;
    }
    handle->setParent(g_foreign);
    g_windows.push_back(window);
    start_guard();
    if (g_fit_timer == nullptr){
        g_fit_timer = new QTimer(QCoreApplication::instance());
        g_fit_timer->setInterval(100);
        QObject::connect(g_fit_timer, &QTimer::timeout, QCoreApplication::instance(), []{
            fit_windows();
        });
        g_fit_timer->start();
    }
    fit_windows();
    return true;
#else
    (void)window;
    return false;
#endif
}

int count_top_level_windows(qint64 pid){
#ifdef _WIN32
    TopSearch search;
    search.pid = (DWORD)pid;
    EnumWindows(collect_top, (LPARAM)&search);
    return search.count;
#else
    (void)pid;
    return 0;
#endif
}

QString describe_process_windows(qint64 pid){
#ifdef _WIN32
    struct Listing{
        DWORD pid = 0;
        QStringList lines;
    } listing;
    listing.pid = (DWORD)pid;
    EnumWindows([](HWND window, LPARAM parameter) -> BOOL{
        Listing& found = *(Listing*)parameter;
        DWORD owner_pid = 0;
        GetWindowThreadProcessId(window, &owner_pid);
        if (owner_pid != found.pid || found.lines.size() >= 12){
            return TRUE;
        }
        wchar_t title[128] = {0};
        wchar_t kind[128] = {0};
        GetWindowTextW(window, title, 127);
        GetClassNameW(window, kind, 127);
        RECT area = {0, 0, 0, 0};
        GetWindowRect(window, &area);
        found.lines.append(
            QString("'%1' (%2) %3, %4x%5%6")
                .arg(QString::fromWCharArray(title))
                .arg(QString::fromWCharArray(kind))
                .arg(IsWindowVisible(window) ? "visible" : "hidden")
                .arg(area.right - area.left)
                .arg(area.bottom - area.top)
                .arg(GetWindow(window, GW_OWNER) != nullptr ? ", with an owner" : "")
        );
        return TRUE;
    }, (LPARAM)&listing);
    return listing.lines.isEmpty() ? QString("no window at all") : listing.lines.join("; ");
#else
    (void)pid;
    return QString();
#endif
}

bool focus_child_window(quintptr parent, qint64 pid){
#ifdef _WIN32
    ChildSearch search;
    search.parent = (HWND)parent;
    search.pid = (DWORD)pid;
    EnumChildWindows(search.parent, collect_child, (LPARAM)&search);
    if (search.found.empty()){
        return false;
    }
    return SetFocus(search.found.front()) != nullptr || GetFocus() == search.found.front();
#else
    (void)parent;
    (void)pid;
    return false;
#endif
}

bool describe_child_window(quintptr parent, qint64 pid, QSize* child_size, QSize* parent_size, bool* visible, bool* child_style){
#ifdef _WIN32
    ChildSearch search;
    search.parent = (HWND)parent;
    search.pid = (DWORD)pid;
    EnumChildWindows(search.parent, collect_child, (LPARAM)&search);
    if (search.found.empty()){
        return false;
    }
    const HWND window = search.found.front();
    RECT inside = {0, 0, 0, 0};
    RECT outside = {0, 0, 0, 0};
    GetClientRect(window, &inside);
    GetClientRect(search.parent, &outside);
    if (child_size != nullptr){
        *child_size = QSize(inside.right - inside.left, inside.bottom - inside.top);
    }
    if (parent_size != nullptr){
        *parent_size = QSize(outside.right - outside.left, outside.bottom - outside.top);
    }
    if (visible != nullptr){
        *visible = IsWindowVisible(window) != 0;
    }
    if (child_style != nullptr){
        *child_style = (GetWindowLongW(window, GWL_STYLE) & WS_CHILD) != 0;
    }
    return true;
#else
    (void)parent;
    (void)pid;
    (void)child_size;
    (void)parent_size;
    (void)visible;
    (void)child_style;
    return false;
#endif
}

int count_child_windows(quintptr parent, qint64 pid){
#ifdef _WIN32
    ChildSearch search;
    search.parent = (HWND)parent;
    search.pid = (DWORD)pid;
    EnumChildWindows(search.parent, collect_child, (LPARAM)&search);
    return (int)search.found.size();
#else
    (void)parent;
    (void)pid;
    return 0;
#endif
}


//  ---------------------------------------------------------------------
//  The probe: a window that is a colour, in the window it was given
//  ---------------------------------------------------------------------

namespace{

class ProbeWindow : public QWidget{
public:
    ProbeWindow()
        : QWidget(nullptr, Qt::Window | Qt::FramelessWindowHint)
    {
        setWindowTitle("Claude GG embedding probe");
    }
protected:
    virtual void paintEvent(QPaintEvent*) override{
        QPainter painter(this);
        painter.fillRect(rect(), QColor(200, 30, 30));
        painter.setPen(Qt::white);
        QFont font = painter.font();
        font.setPixelSize(32);
        painter.setFont(font);
        painter.drawText(rect(), Qt::AlignCenter, "an installation, embedded");
    }
};

}

int run_embed_probe(QApplication& application){
    Logger& logger = global_logger_tagged();
    ProbeWindow window;
    const bool embedded = embed_instance_window(&window);
    logger.log(std::string("Embedding probe: ") + (embedded ? "the window is a child of the window it was given." : "no window was given, or it is not there."));
    if (!embedded){
        return 2;
    }
    window.show();

    //  As an installation does, when it is not the first: a link that the main
    //  window can ask to close it on, and a status that says it runs (the
    //  main window shows that in its list).
    std::unique_ptr<InstanceLink> link;
    std::unique_ptr<QTimer> report;
    const std::string id = current_instance();
    if (id != MAIN_INSTANCE){
        link = std::make_unique<InstanceLink>(
            instance_link_name(shared_base_path(), QString::fromStdString("i" + id)),
            [&application](const QString& command){
                if (command == "close"){
                    QMetaObject::invokeMethod(&application, []{
                        QCoreApplication::quit();
                    }, Qt::QueuedConnection);
                }
            }
        );
        const QString folder = InstanceRegistry(shared_base_path()).folder(QString::fromStdString(id));
        const qint64 pid = QCoreApplication::applicationPid();
        auto write = [folder, pid]{
            write_instance_report_to(folder, pid, QDateTime::currentMSecsSinceEpoch(), "games", "Embedding probe", QImage());
        };
        write();
        report = std::make_unique<QTimer>();
        report->setInterval(1000);
        QObject::connect(report.get(), &QTimer::timeout, report.get(), write);
        report->start();
    }

    //  A minute at most, for a probe that nobody asked to go. (It goes when the
    //  window it was given goes: see start_guard().)
    QTimer watch;
    watch.setInterval(250);
    int ticks = 0;
    QObject::connect(&watch, &QTimer::timeout, &application, [&]{
        ticks++;
        if (ticks > 240){
            application.quit();
        }
    });
    watch.start();
    application.exec();
    logger.log("Embedding probe: ended.");
    return 0;
}


//  ---------------------------------------------------------------------
//  The test: a window, a probe in it, and what Windows says about both
//  ---------------------------------------------------------------------

namespace{

void wait_for(int msec){
    QEventLoop loop;
    QTimer::singleShot(msec, &loop, &QEventLoop::quit);
    loop.exec();
}

}

int run_embed_test(QApplication& application, const QString& folder){
    (void)application;
    Logger& logger = global_logger_tagged();
    QStringList report;
    int wrong = 0;
    auto check = [&](bool fine, const QString& what){
        report << (fine ? "ok:     " : "FAILED: ") + what;
        if (!fine){
            wrong++;
            logger.log("Embedding test: FAILED: " + what.toStdString(), COLOR_RED);
        }
    };
    auto finish = [&]() -> int{
        if (!folder.isEmpty()){
            QDir().mkpath(folder);
            QFile file(folder + "/embed-test.txt");
            if (file.open(QIODevice::WriteOnly | QIODevice::Truncate)){
                QTextStream(&file) << report.join("\n") << "\n";
            }
        }
        logger.log(
            wrong == 0
                ? "Embedding test: passed."
                : "Embedding test: " + std::to_string(wrong) + " failed.",
            wrong == 0 ? COLOR_BLUE : COLOR_RED
        );
        return wrong == 0 ? 0 : 1;
    };

#ifndef _WIN32
    report << "skipped: embedding is for Windows";
    return finish();
#else
    //  The main window, with a place in it for an installation.
    QWidget host(nullptr, Qt::Window | Qt::FramelessWindowHint);
    host.resize(900, 560);
    QWidget* place = new QWidget(&host);
    place->setAttribute(Qt::WA_NativeWindow, true);
    place->setGeometry(0, 0, 900, 560);
    host.show();
    place->show();
    host.raise();
    wait_for(300);
    const quintptr place_window = (quintptr)place->winId();

    //  The installation (the probe), told where its windows go.
    QProcess child;
    child.setProgram(QCoreApplication::applicationFilePath());
    child.setArguments(QStringList{EMBED_PROBE_OPTION, EMBED_IN_OPTION, QString::number((qulonglong)place_window)});
    child.setProcessChannelMode(QProcess::ForwardedChannels);
    child.start();
    check(child.waitForStarted(20000), "the probe starts as a process of its own");
    if (child.state() == QProcess::NotRunning){
        return finish();
    }
    const qint64 pid = child.processId();

    //  Its window is there, in the place we made.
    int children = 0;
    for (int tries = 0; tries < 150 && children == 0; tries++){
        wait_for(200);
        children = count_child_windows(place_window, pid);
    }
    check(children >= 1, "the probe has made a window, and it is a child of the place in this window (" + QString::number(children) + ")");
    if (children == 0){
        child.kill();
        child.waitForFinished(5000);
        return finish();
    }

    //  It is visible and fills the place.
    ChildSearch search;
    search.parent = (HWND)place_window;
    search.pid = (DWORD)pid;
    EnumChildWindows(search.parent, collect_child, (LPARAM)&search);
    const HWND window = search.found.front();
    RECT place_rect = {0, 0, 0, 0};
    RECT window_rect = {0, 0, 0, 0};
    bool fills = false;
    for (int tries = 0; tries < 50 && !fills; tries++){
        wait_for(100);
        if (GetClientRect(search.parent, &place_rect) && GetClientRect(window, &window_rect)){
            fills =
                std::abs((window_rect.right - window_rect.left) - (place_rect.right - place_rect.left)) <= 2 &&
                std::abs((window_rect.bottom - window_rect.top) - (place_rect.bottom - place_rect.top)) <= 2;
        }
    }
    check(IsWindowVisible(window) != 0, "its window is visible");
    check(fills, "its window is as large as the place (" +
        QString::number(window_rect.right - window_rect.left) + "x" + QString::number(window_rect.bottom - window_rect.top) + " in " +
        QString::number(place_rect.right - place_rect.left) + "x" + QString::number(place_rect.bottom - place_rect.top) + ")");
    check((GetWindowLongW(window, GWL_STYLE) & WS_CHILD) != 0, "it is a child window, with no frame and no place on the taskbar");

    //  The place follows when the window is made larger.
    host.resize(1000, 600);
    place->setGeometry(0, 0, 1000, 600);
    bool follows = false;
    for (int tries = 0; tries < 50 && !follows; tries++){
        wait_for(100);
        if (GetClientRect(search.parent, &place_rect) && GetClientRect(window, &window_rect)){
            follows =
                std::abs((window_rect.right - window_rect.left) - (place_rect.right - place_rect.left)) <= 2 &&
                std::abs((window_rect.bottom - window_rect.top) - (place_rect.bottom - place_rect.top)) <= 2;
        }
    }
    check(follows, "its window follows when the place is made larger");

    //  What is on the screen: red, as the probe paints it.
    wait_for(500);
    if (QScreen* screen = host.screen()){
        const QPoint origin = place->mapToGlobal(QPoint(0, 0));
        const QImage shot = screen->grabWindow(0, origin.x(), origin.y(), place->width(), place->height()).toImage();
        if (!folder.isEmpty()){
            QDir().mkpath(folder);
            shot.save(folder + "/embed-test.png");
        }
        const QColor color = shot.isNull() ? QColor() : shot.pixelColor(shot.width() / 4, shot.height() / 4);
        check(
            !shot.isNull() && color.red() > 150 && color.green() < 90 && color.blue() < 90,
            "the place is red on the screen, as the probe paints it (" +
                (shot.isNull() ? QString("no picture") : QString("%1,%2,%3").arg(color.red()).arg(color.green()).arg(color.blue())) + ")"
        );
    }else{
        check(false, "the window is on a screen");
    }

    //  The probe goes with the window it was given.
    host.close();
    place->hide();
    host.hide();
    delete place;
    //  The window of this process keeps answering while it waits: a window that
    //  is in another one is tied to it, and the one that holds it must not stand
    //  still while the other is busy with it.
    bool ended = false;
    for (int tries = 0; tries < 75 && !ended; tries++){
        wait_for(200);
        ended = child.state() == QProcess::NotRunning;
    }
    if (!ended){
        child.kill();
        child.waitForFinished(5000);
    }
    check(ended && child.exitStatus() == QProcess::NormalExit && child.exitCode() == 0,
        "the probe ends by itself when the window it was given goes (" +
        QString(ended ? ("exit code " + QString::number(child.exitCode())) : QString("it did not end")) + ")");
    return finish();
#endif
}


}
}
