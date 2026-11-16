"""Навигация по разделам, а не по отдельным действиям.

История привязана к (chat_id, message_id). Изменение параметра на открытом
экране и перелистывание прогноза не добавляют новый уровень истории.
Возврат восстанавливает текст и клавиатуру без повторного погодного API.
"""

import logging

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest

logger = logging.getLogger(__name__)
_MAX_DEPTH = 24
_MAX_MESSAGES = 40


def _key(query):
    msg = query.message
    return f'{msg.chat_id}:{msg.message_id}'


def _state(context):
    return context.user_data.setdefault('_navigation', {})


def _snapshot(query):
    msg = query.message
    rich = getattr(msg, 'text_html', None)
    plain = getattr(msg, 'text', None)
    if rich:
        return rich, getattr(msg, 'reply_markup', None), 'HTML'
    if plain:
        return plain, getattr(msg, 'reply_markup', None), None
    return None


def _page_id(callback):
    """Группируем действия, обновляющие одну логическую страницу."""
    data = callback or ''
    if data.startswith('settings_set_language_'):
        return 'settings_language'
    if data.startswith('settings_set_'):
        rest = data[len('settings_set_'):]
        return 'settings_choice:' + rest.rsplit('_', 1)[0]
    if data.startswith('settings_toggle_extra_'):
        return 'settings_extra_data'
    if data.startswith('settings_toggle_button_'):
        return 'settings_extra_buttons'
    settings_choices = {
        'settings_temp': 'temperature',
        'settings_pressure': 'pressure',
        'settings_time': 'time_format',
        'settings_wind': 'wind_speed',
    }
    if data in settings_choices:
        return 'settings_choice:' + settings_choices[data]
    if data in ('settings_back', 'settings_menu'):
        return 'settings_menu'
    if data in ('settings_help', 'settings_help_info'):
        return 'settings_help'
    if data in ('settings_lang_ru', 'settings_lang_en') or data.startswith('settings_set_language_'):
        return 'settings_language'
    if data.startswith('hourly_page_') or data.startswith('hourly_'):
        return 'hourly_forecast'
    if data.startswith(('rain_today_', 'rain_tomorrow_', 'rain_')):
        return 'rain_forecast'
    if data.startswith('day_forecast_'):
        return 'day_forecast'
    if data.startswith('changelog_pre_1_1_'):
        return 'changelog_pre'
    if data == 'changelog_release_1_1':
        return 'changelog_release_1_1'
    if data.startswith('changelog_'):
        return 'changelog'
    if data in ('favorites',) or data.startswith(('remove_compare_', 'remove_favorite_fav_')):
        return 'favorites'
    if data.startswith('favorite_compare_'):
        return 'favorite_compare'
    if data.startswith(('weather_fav_', 'weather_')):
        return 'weather'
    if data.startswith('view_compare_city_'):
        return 'weather'
    if data.startswith(('admin_user_detail_', 'admin_demote_')):
        return 'admin_user_detail'
    if data.startswith('admin_direct_message_'):
        return 'admin_user_message'
    if data.startswith('admin_promote_'):
        return 'admin_user_promote'
    if data.startswith('extra_'):
        return 'extra_data'
    if data.startswith('week_forecast_'):
        return 'week_forecast'
    if data.startswith('week_summary_tomorrow_'):
        return 'week_summary_tomorrow'
    if data.startswith('week_summary_'):
        return 'week_summary'
    return data


def _is_back_button(button):
    callback = getattr(button, 'callback_data', None)
    if not callback or callback == 'nav_back':
        return False
    text = (getattr(button, 'text', '') or '').casefold()
    # «◀ Назад» при перелистывании — не возврат в родительский раздел.
    if callback.startswith('hourly_page_'):
        return False
    return ('назад' in text or 'back' in text or 'к списку версий' in text)


def _with_real_back(markup):
    if not markup or not getattr(markup, 'inline_keyboard', None):
        return markup
    changed = False
    rows = []
    for row in markup.inline_keyboard:
        buttons = []
        for button in row:
            if _is_back_button(button):
                buttons.append(InlineKeyboardButton(button.text, callback_data='nav_back'))
                changed = True
            else:
                buttons.append(button)
        rows.append(buttons)
    return InlineKeyboardMarkup(rows) if changed else markup


async def edit(query, context, text, reply_markup=None, parse_mode=None, remember=True):
    """Обновить экран; сохранять предыдущий только при смене *раздела*."""
    markup = _with_real_back(reply_markup)
    key = _key(query)
    state = _state(context)
    entry = state.setdefault(key, {'history': [], 'current': None, 'page': None})
    old = entry['current'] or _snapshot(query)
    old_page = entry.get('page')
    new_page = _page_id(getattr(query, 'data', ''))

    if markup is None and old and old[0] != text:
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton('↩ Назад / Back', callback_data='nav_back')
        ]])
    new = (text, markup, parse_mode)
    try:
        result = await query.edit_message_text(text, reply_markup=markup, parse_mode=parse_mode)
    except BadRequest as exc:
        if 'not modified' not in str(exc).lower():
            logger.warning('Ошибка обновления экрана: %s', type(exc).__name__)
            return None
        result = None

    # На странице часы 1/4 -> 2/4 или переключатель OFF -> ON остаёмся
    # на том же уровне. В history должен остаться родительский экран.
    if remember and old and old[0] and old != new and old_page != new_page:
        entry['history'].append((*old, old_page))
        if len(entry['history']) > _MAX_DEPTH:
            del entry['history'][:-_MAX_DEPTH]
    entry['current'] = new
    entry['page'] = new_page
    if len(state) > _MAX_MESSAGES:
        for obsolete in list(state)[:-_MAX_MESSAGES]:
            if obsolete != key:
                state.pop(obsolete, None)
    return result


async def edit_markup(query, context, reply_markup):
    """Переключение кнопки не добавляет новую страницу."""
    markup = _with_real_back(reply_markup)
    result = await query.edit_message_reply_markup(reply_markup=markup)
    entry = _state(context).get(_key(query))
    if entry and entry.get('current'):
        text, _, mode = entry['current']
        entry['current'] = (text, markup, mode)
    return result


async def back(query, context, lang='rus'):
    entry = _state(context).get(_key(query))
    if not entry or not entry['history']:
        await query.answer('Нет предыдущей страницы' if lang == 'rus' else 'No previous page')
        return False
    text, markup, mode, page = entry['history'][-1]
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode=mode)
    except BadRequest as exc:
        if 'not modified' not in str(exc).lower():
            logger.warning('Ошибка возврата на предыдущую страницу: %s', type(exc).__name__)
            return False
    entry['history'].pop()
    entry['current'] = (text, markup, mode)
    entry['page'] = page
    return True
