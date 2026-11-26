/*  ClaudeGG Panel (a panel inside the window)
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include <algorithm>
#include <QApplication>
#include <QEvent>
#include <QFrame>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QLabel>
#include <QMouseEvent>
#include <QPainter>
#include <QPushButton>
#include <QScrollArea>
#include <QVBoxLayout>
#include "ClaudeGG_Embed.h"
#include "ClaudeGG_Language.h"
#include "ClaudeGG_Panel.h"

namespace PokemonAutomation{
namespace ClaudeGG{


PanelOverlay::PanelOverlay(QWidget* parent)
    : QWidget(parent)
    , m_card(new QFrame(this))
    , m_title(nullptr)
    , m_close(nullptr)
    , m_scroll(nullptr)
    , m_plain(nullptr)
    , m_plain_layout(nullptr)
    , m_card_layout(nullptr)
{
    setObjectName("ppPanelOverlay");
    setFocusPolicy(Qt::StrongFocus);
    setMouseTracking(true);
    hide();
    if (parent != nullptr){
        parent->installEventFilter(this);
    }

    m_card->setObjectName("ppPanelCard");
    m_card->setFrameShape(QFrame::NoFrame);
    m_card->setAutoFillBackground(true);
    m_card->setStyleSheet(
        "QFrame#ppPanelCard{background: palette(window); border: 1px solid palette(mid); border-radius: 16px;}"
    );
    m_card_layout = new QVBoxLayout(m_card);
    m_card_layout->setContentsMargins(18, 12, 18, 18);
    m_card_layout->setSpacing(10);

    QHBoxLayout* head = new QHBoxLayout();
    head->setContentsMargins(0, 0, 0, 0);
    m_title = new QLabel(m_card);
    m_title->setObjectName("ppPanelTitle");
    QFont font = m_title->font();
    font.setBold(true);
    if (font.pointSizeF() > 0){
        font.setPointSizeF(font.pointSizeF() * 1.25);
    }
    m_title->setFont(font);
    head->addWidget(m_title, 1);
    m_close = new QPushButton(QString::fromUtf8("\xE2\x9C\x95"), m_card);
    m_close->setObjectName("ppPanelClose");
    m_close->setToolTip(tr_ui("Close") + " (Esc)");
    m_close->setFlat(true);
    m_close->setFocusPolicy(Qt::NoFocus);
    m_close->setCursor(Qt::PointingHandCursor);
    m_close->setFixedSize(34, 34);
    QObject::connect(m_close, &QPushButton::clicked, this, [this]{
        hide_panel();
    });
    head->addWidget(m_close, 0, Qt::AlignTop);
    m_card_layout->addLayout(head);

    //  A narrow card scrolls what does not fit; a wide one is the content's own size.
    m_scroll = new QScrollArea(m_card);
    m_scroll->setObjectName("ppPanelScroll");
    m_scroll->setFrameShape(QFrame::NoFrame);
    m_scroll->setWidgetResizable(true);
    m_scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_scroll->hide();
    m_card_layout->addWidget(m_scroll, 1);
    m_plain = new QWidget(m_card);
    m_plain->setObjectName("ppPanelBody");
    m_plain_layout = new QVBoxLayout(m_plain);
    m_plain_layout->setContentsMargins(0, 0, 0, 0);
    m_plain_layout->setSpacing(0);
    m_plain->hide();
    m_card_layout->addWidget(m_plain, 1);
    m_card->hide();
}

PanelOverlay::~PanelOverlay(){
    //  What the panel does not own goes back to nobody: the owner deletes it.
    if (m_content != nullptr && !m_options.own){
        m_content->setParent(nullptr);
    }
}

QRect PanelOverlay::card_rect() const{
    return m_card->geometry();
}

void PanelOverlay::put_away(){
    if (m_content == nullptr){
        return;
    }
    QWidget* content = m_content;
    m_content.clear();
    content->hide();
    if (m_options.own){
        content->setParent(nullptr);
        content->deleteLater();
    }
    //  (The owner of the rest keeps it, hidden, in the card, ready for the next time.)
}

void PanelOverlay::show_panel(const QString& title, QWidget* content, const Options& options){
    if (content == nullptr){
        return;
    }
    if (m_open && m_content == content){
        place();
        raise();
        return;
    }
    if (m_content != nullptr){
        put_away();
    }
    if (!m_open){
        m_previous_focus = QApplication::focusWidget();
    }
    m_options = options;
    m_title_text = title;
    m_title->setText(title);
    m_content = content;
    if (options.wide){
        m_scroll->hide();
        content->setParent(m_plain, Qt::Widget);
        m_plain_layout->addWidget(content);
        m_plain->show();
    }else{
        m_plain->hide();
        m_scroll->setWidget(content);
        m_scroll->show();
    }
    //  (A dialog would put itself beside its parent when it is shown: here it stays where the card puts it.)
    content->setAttribute(Qt::WA_Moved, true);
    content->show();
    m_open = true;
    place();
    show();
    raise();
    m_card->show();
    //  The keys (Esc) come to the panel; in a window that is held inside another one the
    //  keyboard has to be asked for.
    setFocus(Qt::OtherFocusReason);
    take_keyboard(this);
}

void PanelOverlay::hide_panel(){
    if (!m_open){
        return;
    }
    m_open = false;
    //  A scroll area gives its widget up when another comes (or it is deleted with it): take it out first.
    if (m_content != nullptr && !m_options.wide){
        m_scroll->takeWidget();
    }
    put_away();
    m_title_text.clear();
    m_card->hide();
    hide();
    if (m_previous_focus != nullptr){
        m_previous_focus->setFocus(Qt::OtherFocusReason);
    }
    m_previous_focus.clear();
    if (on_closed){
        on_closed();
    }
}

void PanelOverlay::place(){
    QWidget* parent = parentWidget();
    if (parent == nullptr){
        return;
    }
    setGeometry(parent->rect());
    const int margin = 28;
    const int room_w = std::max(200, width() - 2 * margin);
    const int room_h = std::max(160, height() - 2 * margin);
    int w = room_w;
    int h = room_h;
    if (!m_options.wide && m_content != nullptr){
        //  As large as the content wants at the width that fits, and no larger than the window.
        w = std::min(room_w, 760);
        const int chrome_w = 36;
        const int chrome_h = 12 + 34 + 10 + 18 + 4;
        int wanted = 0;
        if (m_content->hasHeightForWidth()){
            wanted = m_content->heightForWidth(std::max(100, w - chrome_w - 4));
        }
        if (wanted <= 0){
            wanted = m_content->sizeHint().height();
        }
        h = std::min(room_h, std::max(240, wanted + chrome_h + 4));
    }
    m_card->setGeometry((width() - w) / 2, (height() - h) / 2, w, h);
}

bool PanelOverlay::eventFilter(QObject* watched, QEvent* event){
    if (watched == parentWidget() && event->type() == QEvent::Resize && m_open){
        place();
    }
    return QWidget::eventFilter(watched, event);
}

void PanelOverlay::paintEvent(QPaintEvent*){
    QPainter painter(this);
    painter.fillRect(rect(), QColor(0, 0, 0, 150));
}

void PanelOverlay::mousePressEvent(QMouseEvent* event){
    //  A click beside the card closes it; nothing goes through to the window below.
    if (!m_card->geometry().contains(event->pos())){
        hide_panel();
    }
    event->accept();
}
void PanelOverlay::mouseReleaseEvent(QMouseEvent* event){
    event->accept();
}
void PanelOverlay::mouseMoveEvent(QMouseEvent* event){
    event->accept();
}
void PanelOverlay::wheelEvent(QWheelEvent* event){
    event->accept();
}

void PanelOverlay::keyPressEvent(QKeyEvent* event){
    //  What the content does not use (a search box ignores Esc) comes up to here.
    if (event->key() == Qt::Key_Escape){
        event->accept();
        hide_panel();
        return;
    }
    event->accept();
}


}
}
