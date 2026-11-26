/*  ClaudeGG Panel (a panel inside the window)
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 *  Claude GG is one program in one window. What used to open as a window of its
 *  own (the output log, the diagram of the buttons, "About") is shown in a panel
 *  that lies over the window instead: a card in the middle, with a title and a
 *  button to close it, on a dimmed ground. Esc, a click beside the card and
 *  that button close it. No window comes of it, so nothing is left behind when
 *  the program closes.
 *
 *  The panel holds the widget that was a window: its owner keeps it (it is
 *  hidden again when the panel is closed, not deleted), or the panel owns it.
 *
 */

#ifndef PokemonAutomation_ClaudeGG_Panel_H
#define PokemonAutomation_ClaudeGG_Panel_H

#include <functional>
#include <QPointer>
#include <QString>
#include <QWidget>

class QFrame;
class QLabel;
class QPushButton;
class QScrollArea;
class QVBoxLayout;

namespace PokemonAutomation{
namespace ClaudeGG{


class PanelOverlay : public QWidget{
public:
    //  Over the whole of "parent" (it follows the size of the parent). Hidden.
    explicit PanelOverlay(QWidget* parent);
    virtual ~PanelOverlay() override;

    struct Options{
        //  The card takes most of the window (the log, a picture): otherwise it is as
        //  large as its content wants, and the content scrolls when it is not
        //  that small.
        bool wide = false;
        //  The panel deletes the content when it is closed.
        bool own = false;
    };

    //  Shows "content" under the title. What was shown is put away.
    void show_panel(const QString& title, QWidget* content, const Options& options);
    void show_panel(const QString& title, QWidget* content){
        show_panel(title, content, Options());
    }
    //  Closes the panel (nothing if none is open). The content is hidden.
    void hide_panel();

    bool is_open() const{
        return m_open;
    }
    const QString& title() const{
        return m_title_text;
    }
    QWidget* content() const{
        return m_content;
    }
    //  The card, for the test: where it is in the overlay.
    QRect card_rect() const;

    //  Called after the panel was closed (the keyboard goes back to the window).
    std::function<void()> on_closed;

protected:
    virtual void paintEvent(QPaintEvent* event) override;
    virtual void mousePressEvent(QMouseEvent* event) override;
    virtual void mouseReleaseEvent(QMouseEvent* event) override;
    virtual void mouseMoveEvent(QMouseEvent* event) override;
    virtual void wheelEvent(QWheelEvent* event) override;
    virtual void keyPressEvent(QKeyEvent* event) override;
    virtual bool eventFilter(QObject* watched, QEvent* event) override;

private:
    void place();
    void put_away();

    QFrame* m_card;
    QLabel* m_title;
    QPushButton* m_close;
    QScrollArea* m_scroll;
    QWidget* m_plain;               //  the body of a wide card
    QVBoxLayout* m_plain_layout;
    QVBoxLayout* m_card_layout;
    QPointer<QWidget> m_content;
    QString m_title_text;
    Options m_options;
    bool m_open = false;
    QPointer<QWidget> m_previous_focus;
};


}
}
#endif
