/*  ClaudeGG About
 *
 *  Part of ClaudeGG, which is based on Pokemon Automation
 *  (https://github.com/PokemonAutomation/).
 *
 */

#include "Common/Compiler.h"
#include <QCheckBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QPointer>
#include <QPushButton>
#include <QVBoxLayout>
#include "Assistant/Assistant_Http.h"
#include "ClaudeGG_Language.h"
#include "ClaudeGG_Logo.h"
#include "ClaudeGG_Theme.h"
#include "ClaudeGG_Update.h"
#include "ClaudeGG_UpdateDialog.h"
#include "ClaudeGG_About.h"

namespace PokemonAutomation{
namespace ClaudeGG{

namespace{


QString link(const QString& url, const QString& text, const QColor& color){
    return "<a href=\"" + url + "\" style=\"color: " + color.name() + "\">" + text + "</a>";
}

QLabel* paragraph(QWidget& parent, const QString& html){
    QLabel* label = new QLabel(html, &parent);
    label->setTextFormat(Qt::RichText);
    label->setWordWrap(true);
    label->setTextInteractionFlags(Qt::TextBrowserInteraction);
    label->setOpenExternalLinks(true);
    return label;
}


}



std::unique_ptr<QDialog> make_about(QWidget* parent, const AboutInfo& info, Assistant::HttpTransport* transport){
    const ThemeColors& theme = theme_colors();
    //  Links in a color that reads on the window: the accent at night, a
    //  plain blue otherwise.
    const QColor link_color = theme.dark ? theme.accent : QColor(0x0b, 0x5c, 0xc4);

    std::unique_ptr<QDialog> owner = std::make_unique<QDialog>(parent);
    QDialog& dialog = *owner;
    dialog.setWindowTitle(tr_ui("About %1").arg(info.name));
    dialog.setMinimumWidth(560);

    QVBoxLayout* layout = new QVBoxLayout(&dialog);
    layout->setContentsMargins(26, 22, 26, 18);
    layout->setSpacing(12);

    //  The mark, the name and the build.
    QHBoxLayout* head = new QHBoxLayout();
    head->setSpacing(16);
    layout->addLayout(head);
    QLabel* mark = new QLabel(&dialog);
    const int MARK = 64;
    QPixmap pixmap = app_icon_pixmap((int)(MARK * dialog.devicePixelRatioF() + 0.5));
    pixmap.setDevicePixelRatio(dialog.devicePixelRatioF());
    mark->setPixmap(pixmap);
    mark->setFixedSize(MARK, MARK);
    head->addWidget(mark, 0, Qt::AlignTop);
    QVBoxLayout* names = new QVBoxLayout();
    names->setSpacing(0);
    head->addLayout(names, 1);
    QLabel* name = new QLabel(info.name, &dialog);
    name->setObjectName("ppAboutTitle");
    name->setFont(display_font(42));
    names->addWidget(name);
    QLabel* tagline = new QLabel(
        tr_ui("Game automation for any console, starting with the Nintendo Switch. Run programs, or build and fix them with Claude."),
        &dialog
    );
    tagline->setWordWrap(true);
    names->addWidget(tagline);
    names->addSpacing(4);
    QLabel* build = new QLabel(
        tr_ui("Build %1, on %2 %3").arg(info.build, info.upstream_name, info.upstream_version),
        &dialog
    );
    build->setObjectName("ppMuted");
    build->setTextInteractionFlags(Qt::TextSelectableByMouse);
    names->addWidget(build);
    names->addStretch(1);

    layout->addWidget(paragraph(dialog,
        tr_ui(
            "A program of %1 plays a game on a Nintendo Switch by itself: it watches the "
            "game through a capture card and presses the buttons through a controller board."
        ).arg(info.name)
    ));

    layout->addWidget(paragraph(dialog,
        tr_ui(
            "<b>Claude.</b> The panel \"Claude\" and the program \"Claude Plays\" talk to Claude, the AI "
            "model of Anthropic, with an API key of your own, which Anthropic bills you for. What you "
            "write, what Claude looks up to answer (the log, the options, parts of the source) and, when "
            "it plays, pictures of the game and the text on its screen are sent to Anthropic, and nothing "
            "before you add a key. Its changes to the source go to a branch of their own."
        )
    ));

    layout->addWidget(paragraph(dialog,
        tr_ui(
            "<b>Where it comes from.</b> %1 is a personal fork of %2 (Copyright 2021 Alexander J. Yee "
            "and its contributors), used under the MIT license. The programs for the games and the "
            "documentation they link to are theirs. This fork is not theirs: please do not ask them "
            "for help with it, but use %3."
        ).arg(
            info.name,
            link(info.upstream_url, info.upstream_name, link_color),
            link(info.project_url, tr_ui("this fork's page"), link_color)
        )
    ));

    layout->addWidget(paragraph(dialog,
        tr_ui(
            "<b>Not an official product.</b> %1 is not made, endorsed or supported by "
            "Nintendo, Game Freak, Creatures, The Pokémon Company or Anthropic. The names of the games "
            "belong to their owners and are used here only to say which game a program is for."
        ).arg(info.name)
    ));

    layout->addWidget(paragraph(dialog,
        tr_ui(
            "<b>Licenses.</b> The source is under the MIT license; the builds, with the libraries "
            "they bring along, are for non-commercial use. %1 uses Qt %2 under the LGPL version 3 "
            "(unmodified, as separate libraries) and the typefaces Jersey 20 by Sarah Cadigan-Fried, "
            "Newsreader by The Newsreader Project Authors and Fredoka by The Fredoka Project Authors "
            "under the SIL Open Font License 1.1. The licenses are in the folder \"Licenses\" next "
            "to the program."
        ).arg(info.name, QString::fromLatin1(qVersion()))
    ));

    //  The check for updates: when the button is pressed (and at the start,
    //  ClaudeGG_UpdateDialog.h).
    if (transport != nullptr){
        layout->addWidget(paragraph(dialog,
            tr_ui(
                "<b>Updates.</b> The button, and the program at its start unless you turn that off, "
                "ask github.com for the list of the builds of this fork, and that is all they send. "
                "A newer build can be installed from here: its download is checked against the "
                "SHA-256 its release lists, and your settings stay."
            )
        ));
        QCheckBox* at_start = new QCheckBox(tr_ui("Check for updates when Claude GG starts"), &dialog);
        at_start->setObjectName("ppAboutUpdateAtStart");
        at_start->setChecked(update_check_at_start());
        QObject::connect(at_start, &QCheckBox::toggled, [](bool on){
            set_update_check_at_start(on);
        });
        layout->addWidget(at_start);
        QHBoxLayout* update_row = new QHBoxLayout();
        update_row->setSpacing(12);
        layout->addLayout(update_row);
        QVBoxLayout* update_buttons = new QVBoxLayout();
        update_buttons->setSpacing(8);
        update_row->addLayout(update_buttons);
        QPushButton* check_button = new QPushButton(tr_ui("Check for updates"), &dialog);
        check_button->setObjectName("ppAboutUpdateButton");
        update_buttons->addWidget(check_button, 0, Qt::AlignTop);
        QPushButton* install_button = new QPushButton(tr_ui("Install..."), &dialog);
        install_button->setObjectName("ppAboutInstallButton");
        install_button->hide();
        update_buttons->addWidget(install_button, 0, Qt::AlignTop);
        update_buttons->addStretch(1);
        QLabel* update_result = paragraph(dialog, QString());
        update_result->setObjectName("ppAboutUpdateResult");
        update_row->addWidget(update_result, 1);
        //  The last answer, for the window of the update.
        std::shared_ptr<UpdateResult> last = std::make_shared<UpdateResult>();
        QObject::connect(install_button, &QPushButton::clicked, &dialog, [&dialog, last]{
            //  Over the main window, not the panel that About is in.
            QWidget* main_window = dialog.window()->parentWidget() != nullptr ? dialog.window()->parentWidget()->window() : nullptr;
            show_update_dialog(main_window, *last, false);
        });

        //  The check goes with the button: it stops when the window is closed.
        std::shared_ptr<UpdateCheck> check = std::make_shared<UpdateCheck>(*transport, info.project_url, info.build);
        const QString color = link_color.name();
        QPointer<QPushButton> button_pointer(check_button);
        QPointer<QLabel> result_pointer(update_result);
        QPointer<QPushButton> install_pointer(install_button);
        QDialog* dialog_pointer = &dialog;
        QVBoxLayout* layout_pointer = layout;
        QObject::connect(check_button, &QPushButton::clicked, check_button, [=]{
            if (check->running()){
                return;
            }
            button_pointer->setEnabled(false);
            result_pointer->setText(tr_ui("Checking..."));
            install_pointer->hide();
            check->start([=](const UpdateResult& result){
                button_pointer->setEnabled(true);
                result_pointer->setText(update_text(result, color));
                *last = result;
                install_pointer->setVisible(result.state == UpdateState::NEWER_AVAILABLE);
                //  The window grows with the text, and does not shrink.
                layout_pointer->activate();
                const int needed = layout_pointer->totalHeightForWidth(dialog_pointer->width());
                if (needed > dialog_pointer->height()){
                    dialog_pointer->resize(dialog_pointer->width(), needed);
                }
            });
        });
    }

    QLabel* details = new QLabel(
        tr_ui("Compiled for %1 with %2.").arg(info.architecture, info.compiler),
        &dialog
    );
    details->setObjectName("ppMuted");
    details->setTextInteractionFlags(Qt::TextSelectableByMouse);
    layout->addWidget(details);
    layout->addStretch(1);

    QDialogButtonBox* buttons = new QDialogButtonBox(QDialogButtonBox::Close, &dialog);
    layout->addWidget(buttons);
    QObject::connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    QObject::connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);

    //  As tall as its text needs at this width. Left to itself, a window
    //  is at most two thirds of the screen high: on a small screen the
    //  text would be cut off.
    layout->activate();
    const int width = dialog.minimumWidth();
    dialog.resize(width, layout->totalHeightForWidth(width));

    return owner;
}

void show_about(QWidget* parent, const AboutInfo& info){
    std::unique_ptr<Assistant::HttpTransport> transport = Assistant::make_network_transport();
    std::unique_ptr<QDialog> dialog = make_about(parent, info, transport.get());
    dialog->exec();
}



}
}
