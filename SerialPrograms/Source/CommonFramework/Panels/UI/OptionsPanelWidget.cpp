/*  Options Panel Widget
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include "CommonFramework/Panels/UI/PanelElements.h"
#include "ClaudeGG/ClaudeGG_SettingsSearch.h"
#include "OptionsPanelWidget.h"

namespace PokemonAutomation{

template class RegisterUiStateQtWidget<OptionsPanelWidget>;




OptionsPanelWidget::OptionsPanelWidget(
    QWidget& parent,
    OptionsPanelSession& session
)
    : QWidget(&parent)
{
    populate_panel_widget(
        *this,
        session.descriptor(),
        nullptr,
        session.options(),
        {make_actions_bar(*this, session)}
    );
    //  ClaudeGG: a search field above the options.
    ClaudeGG::add_options_search(*this);
}




}
