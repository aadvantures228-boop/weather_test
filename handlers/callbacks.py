from handlers import navigation
"""Маршрутизация всех кнопок Beta 1.1 без лишних платных запросов."""
import asyncio
import logging
import time

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext
from telegram.error import BadRequest

import storage
import favorites
import utils
from handlers import admin, messages
from handlers import settings as settings_module
from handlers.features.compare import compare_cities
from weather_api import get_weather_data, get_city_details, same_city
from config.env import ADMIN_ID
from config.texts import ui
from html import escape
from config.emojis import *

logger = logging.getLogger(__name__)


async def _edit(query, context, text, markup=None, parse_mode=None):
    try:
        await navigation.edit(query, context, text, reply_markup=markup, parse_mode=parse_mode)
    except BadRequest as exc:
        if 'not modified' not in str(exc).lower():
            logger.warning('Не удалось обновить callback: %s', type(exc).__name__)


async def _pending(query, lang, task):
    """Показываем ожидание для длительной операции и всегда удаляем его."""
    notice = None
    try:
        notice = await query.message.reply_text(ui('processing',lang))
    except Exception:
        logger.debug('Не удалось показать ожидание')
    try:
        return await task
    finally:
        if notice:
            try:
                await notice.delete()
            except Exception:
                logger.debug('Не удалось удалить ожидание')


async def _resolve_favorite(context, query, user_id, key):
    # Множество открытых старых меню не должны смешивать fav_0 из разных сообщений.
    msg_map = context.user_data.get('fav_maps_by_message', {}).get(query.message.message_id, {})
    city = msg_map.get(key) or context.user_data.get('fav_map', {}).get(key)
    if city:
        return city
    if key.startswith('fav_') and key[4:].isdigit():
        favorites = await storage.get_user_favorites(context, user_id)
        idx = int(key[4:])
        return favorites[idx] if idx < len(favorites) else None
    return None


async def _source(payload, context, query, user_id):
    """(city, from_favorites, favorite_id, from_compare)."""
    if payload.startswith('fav_fav_'):
        payload = payload[4:]  # совместимость с ошибкой из Beta 1.1
    if payload.startswith('fav_') and payload[4:].isdigit():
        city = await _resolve_favorite(context, query, user_id, payload)
        return city, True, payload, False
    if payload.startswith('cmp_'):
        return utils.decode_city(payload[4:]), False, None, True
    decoded = utils.decode_city(payload)
    if decoded and decoded != payload and decoded.startswith('cmp_'):
        return decoded[4:], False, None, True
    return decoded, False, None, False


async def _weather(query, context, city, lang, region, is_admin,
                   from_favorites=False, safe_id=None, from_compare=False, force_refresh=False):
    settings = await storage.get_user_settings(context, query.from_user.id)
    level = await storage.get_api_units(context, query.from_user.id)
    info, text = await asyncio.to_thread(get_weather_data, city, lang, level, settings, force_refresh)
    if not info:
        await _edit(query, context, text)
        return
    fav = await storage.is_city_in_favorites(context, query.from_user.id, city)
    context.user_data['came_from_compare'] = from_compare
    context.user_data['came_from_favorites'] = from_favorites
    context.user_data['fav_safe_id'] = safe_id
    await _edit(query, context, text, utils.create_weather_keyboard(
        city, fav, region, lang,
        from_favorites=from_favorites, safe_id=safe_id,
        back_to_compare=from_compare, is_admin=is_admin, settings=settings,
        is_current_region=bool(region and (city.casefold() == region.casefold() or
            await asyncio.to_thread(same_city, city, region)))))


async def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data or ''
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)
    region = await storage.get_user_region(context, user_id)
    is_admin = user_id == ADMIN_ID
    # Быстро подтверждаем нажатие независимо от скорости HTTP-запросов.
    try:
        await query.answer()
    except BadRequest:
        pass

    if data == 'nav_back':
        admin.clear_direct_action(context)
        # При возврате из формы ввода оставшееся состояние не должно поглощать чат.
        context.user_data['compare_step'] = 0
        context.user_data.pop('compare_city_1', None)
        context.user_data['awaiting_region_from_settings'] = False
        context.user_data['awaiting_activation_key'] = False
        for state in ('admin_awaiting_broadcast', 'admin_awaiting_user_id', 'admin_awaiting_user_message'):
            if context.bot_data.get(state) == user_id:
                context.bot_data.pop(state, None)
        context.bot_data.pop('admin_target_user_id', None)
        return await navigation.back(query, context, lang)

    # Администратор: права дополнительно проверяются внутри admin.py.
    admin_routes = {
        'admin_panel': admin.admin_panel, 'admin_users_list': admin.show_users_list,
        'admin_broadcast': admin.start_broadcast,
        'admin_broadcast_user': admin.start_broadcast_user,
        'admin_check_users': admin.confirm_user_check,
        'admin_check_users_confirm': admin.check_all_regions,
    }
    if data in admin_routes:
        admin.clear_direct_action(context)
        return await admin_routes[data](update, context)
    if data.startswith('admin_user_detail_'):
        admin.clear_direct_action(context)
        return await admin.show_user_detail(update, context)
    if data.startswith('admin_direct_message_'):
        return await admin.start_user_action(update, context, 'message')
    if data.startswith('admin_promote_'):
        return await admin.start_user_action(update, context, 'promote')
    if data.startswith('admin_demote_'):
        return await admin.demote_user(update, context)

    # Настройки: точные имена имеют приоритет над общими префиксами.
    setting_routes = {
        'settings_menu': settings_module.show_settings_menu,
        'settings_back': settings_module.show_settings_menu,
        'settings_language': settings_module.show_language_settings,
        'settings_display': settings_module.show_display_settings,
        'settings_region': settings_module.show_region_settings,
        'settings_help': settings_module.show_help,
        'settings_help_info': settings_module.show_help_info,
        'settings_change_region': settings_module.start_region_change,
        'settings_extra_data': settings_module.show_extra_data_settings,
        'settings_extra_buttons': settings_module.show_extra_buttons_settings,
    }
    if data in setting_routes:
        if data in ('settings_menu', 'settings_region'):
            context.user_data['awaiting_region_from_settings'] = False
        return await setting_routes[data](update, context)
    if data == 'settings_lang_ru':
        return await settings_module.change_language(update, context, 'rus')
    if data == 'settings_lang_en':
        return await settings_module.change_language(update, context, 'eng')
    if data.startswith('settings_set_'):
        return await settings_module.set_setting_value(update, context)
    if data.startswith('settings_toggle_extra_'):
        return await settings_module.toggle_extra_setting(update, context)
    if data.startswith('settings_toggle_button_'):
        return await settings_module.toggle_button_setting(update, context)
    for pref, key in (('settings_temp', 'temperature'), ('settings_pressure','pressure'),
                       ('settings_time','time_format'), ('settings_wind','wind_speed')):
        if data == pref:
            return await settings_module.show_setting_choice(update, context, key)

    if data == 'activation':
        context.user_data['awaiting_activation_key'] = True
        return await _edit(query, context, f'{ACTIVATION_KEY} ' +
            ('Введите ключ активации сообщением в чат. /cancel — отменить.' if lang == 'rus' else 'Send your activation key in chat. /cancel to cancel.'), InlineKeyboardMarkup([[InlineKeyboardButton(f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back'), callback_data='nav_back')]]))

    if data == 'favorites':
        context.user_data['came_from_favorites'] = False
        context.user_data['fav_safe_id'] = None
        return await _pending(query, lang, messages.favorites(update, context))
    if data == 'clear_all_favorites':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f'{CHECK} ' + ('Да' if lang == 'rus' else 'Yes'), callback_data='confirm_clear_favorites')],
            [InlineKeyboardButton(f'{CROSS} ' + ('Нет' if lang == 'rus' else 'No'), callback_data='nav_back')]
        ])
        return await _edit(query, context, f'{TRASH} ' + ('Очистить список?' if lang == 'rus' else 'Clear favorites?'), keyboard)
    if data == 'confirm_clear_favorites':
        await storage.clear_user_favorites(context, user_id)
        await storage.clear_user_comparisons(context, user_id)
        return await _edit(query, context, f'{TRASH} ' + ('Список очищен.' if lang == 'rus' else 'Favorites cleared.'), InlineKeyboardMarkup([]))

    # Сохранённые пары в том же списке избранного, без лишних кнопок.
    if data.startswith('favorite_compare_'):
        idx_text = data[len('favorite_compare_'):]
        pairs = await storage.get_user_comparisons(context, user_id)
        pair = next((p for p in pairs if str(p['index']) == idx_text), None)
        if not pair:
            return await _edit(query, context, 'Сравнение не найдено.' if lang == 'rus' else 'Comparison not found.')
        s = await storage.get_user_settings(context, user_id)
        async def render_saved():
            text, error = await asyncio.to_thread(compare_cities, pair['first'], pair['second'], lang, s,
                                               pair.get('first_coords'), pair.get('second_coords'))
            if text:
                context.user_data.setdefault('compare_by_message', {})[query.message.message_id] = [pair['first'], pair['second']]
            return await _edit(query, context, text if text else f'{CROSS} {error}',
                utils.create_compare_result_keyboard(pair['first'], pair['second'], lang, favorite_view=True))
        return await _pending(query, lang, render_saved())
    if data.startswith('remove_compare_'):
        idx_text = data[len('remove_compare_'):]
        if idx_text.isdigit():
            await storage.remove_user_comparison(context, user_id, int(idx_text))
        return await messages.favorites(update, context)

    if data == 'compare_save':
        cities = context.user_data.get('compare_by_message', {}).get(query.message.message_id) or context.user_data.get('last_compare_cities')
        if not cities or len(cities) != 2:
            return await query.answer('Сравнение устарело' if lang == 'rus' else 'Comparison expired', show_alert=True)
        inserted = await storage.add_user_comparison(context, user_id, *cities)
        if not inserted:
            return await query.answer('Уже сохранено или достигнут лимит' if lang == 'rus' else 'Already saved or limit reached', show_alert=True)
        s = await storage.get_user_settings(context, user_id)
        return await navigation.edit_markup(query, context, utils.create_compare_result_keyboard(*cities, lang, settings=s, saved=True))
    if data == 'compare_remove_saved':
        cities = context.user_data.get('compare_by_message', {}).get(query.message.message_id) or context.user_data.get('last_compare_cities')
        if not cities or len(cities) != 2:
            return await query.answer('Сравнение устарело' if lang == 'rus' else 'Comparison expired', show_alert=True)
        await storage.remove_user_comparison_pair(context, user_id, *cities)
        s = await storage.get_user_settings(context, user_id)
        return await navigation.edit_markup(query, context, utils.create_compare_result_keyboard(*cities, lang, settings=s, saved=False))
    if data == 'refresh_compare':
        cities = context.user_data.get('compare_by_message', {}).get(query.message.message_id) or context.user_data.get('last_compare_cities')
        if not cities or len(cities) != 2:
            return await query.answer('Сравнение устарело' if lang == 'rus' else 'Comparison expired', show_alert=True)
        now = time.monotonic()
        if now - context.user_data.get('last_refresh_compare', -1e9) < 30:
            return await query.answer('Подождите 30 секунд' if lang == 'rus' else 'Wait 30 seconds')
        context.user_data['last_refresh_compare'] = now
        s = await storage.get_user_settings(context, user_id)
        async def redraw():
            result, error = await asyncio.to_thread(compare_cities, *cities, lang, s)
            return await _edit(query, context, result if result else f'{CROSS} {error}',
                               utils.create_compare_result_keyboard(*cities, lang, settings=s,
                               saved=await favorites.compare_contains(storage.get_db(context), user_id, *cities)))
        # Не расходуем платный кэш ради кнопки обновления.
        return await _pending(query, lang, redraw())

    if data.startswith('refresh_weather_'):
        payload = data[len('refresh_weather_'):]
        city, fav, key, compare = await _source(payload, context, query, user_id)
        if not city:
            return await query.answer('Город не найден' if lang == 'rus' else 'City not found', show_alert=True)
        now = time.monotonic()
        if now - context.user_data.get('last_refresh_weather', -1e9) < 30:
            return await query.answer('Подождите 30 секунд' if lang == 'rus' else 'Wait 30 seconds')
        context.user_data['last_refresh_weather'] = now
        return await _pending(query, lang, _weather(query, context, city, lang, region, is_admin,
                            fav, key, compare, force_refresh=True))

    if data.startswith('weather_fav_'):
        key = data[len('weather_fav_'):]
        city = await _resolve_favorite(context, query, user_id, key)
        if city:
            return await _weather(query, context, city, lang, region, is_admin, True, key)
        return await _edit(query, context, 'Избранное изменилось. Откройте список заново.' if lang == 'rus' else 'Favorites changed. Reopen the list.')

    if data.startswith('weather_'):
        city, fav, key, compare = await _source(data[len('weather_'):], context, query, user_id)
        if city:
            return await _weather(query, context, city, lang, region, is_admin, fav, key, compare)

    if data.startswith('set_region_'):
        city = utils.decode_city(data[len('set_region_'):])
        if city:
            await storage.set_user_region(context, user_id, city)
            # Не делаем погодный запрос ради обновления кнопки.
            s = await storage.get_user_settings(context, user_id)
            markup = utils.create_weather_keyboard(city,
                await storage.is_city_in_favorites(context, user_id, city), city, lang,
                settings=s, is_admin=is_admin)
            try:
                await navigation.edit_markup(query, context, reply_markup=markup)
            except BadRequest:
                pass
        return
    if data.startswith('add_favorite_'):
        city = utils.decode_city(data[len('add_favorite_'):])
        if city:
            await storage.add_user_favorite(context, user_id, city)
            s = await storage.get_user_settings(context, user_id)
            kb = utils.create_weather_keyboard(city,
                await storage.is_city_in_favorites(context, user_id, city), region, lang, settings=s,
                is_current_region=bool(region and (city.casefold() == region.casefold() or await asyncio.to_thread(same_city, city, region))))
            try:
                await navigation.edit_markup(query, context, reply_markup=kb)
            except BadRequest:
                pass
        return
    if data.startswith('remove_favorite_'):
        payload = data[len('remove_favorite_'):]
        if payload.startswith('fav_'):
            city = await _resolve_favorite(context, query, user_id, payload)
            if city:
                await storage.remove_user_favorite(context, user_id, city)
            return await _pending(query, lang, messages.favorites(update, context))
        city = utils.decode_city(payload)
        if city:
            await storage.remove_user_favorite(context, user_id, city)
            s = await storage.get_user_settings(context, user_id)
            kb = utils.create_weather_keyboard(city, False, region, lang, settings=s,
                is_current_region=bool(region and (city.casefold() == region.casefold() or await asyncio.to_thread(same_city, city, region))))
            try:
                await navigation.edit_markup(query, context, reply_markup=kb)
            except BadRequest:
                pass
        return

    if data.startswith('extra_'):
        city, fav, key, compare = await _source(data[len('extra_'):], context, query, user_id)
        if not city:
            return await _edit(query, context, 'Город не найден' if lang == 'rus' else 'City not found')
        # Полностью бесплатные данные о городе.
        settings = await storage.get_user_settings(context, user_id)
        info, _ = await asyncio.to_thread(get_weather_data, city, lang, 'metric', settings)
        details = await asyncio.to_thread(get_city_details, city, lang)
        if not info:
            return await _edit(query, context, 'Данные недоступны' if lang == 'rus' else 'Data unavailable')
        minutes = round(info.get('timezone', 0) / 60)
        sign = '+' if minutes >= 0 else '-'
        hh, mm = divmod(abs(minutes), 60)
        tzstr = f'UTC{sign}{hh:02d}:{mm:02d}'
        # В HTML-коде только координаты: при нажатии Telegram копирует сами числа.
        lat, lon = info.get('lat'), info.get('lon')
        coordinates = f'{lat:.5f}, {lon:.5f}' if lat is not None and lon is not None else '—'
        state = details.get('state')
        region_label = ('Область' if lang == 'rus' else 'Region')
        region_text = f'\n{LOCATION} {region_label}: {escape(str(state))}' if state else ''
        text = ui('extra_location',lang,city=escape(city),
                  country=escape(str(details['country'])),region=region_text,
                  coordinates=coordinates,timezone=tzstr)
        back = f'weather_fav_{key}' if fav else 'back_to_compare' if compare else utils.city_callback('weather_', city)
        return await _edit(query, context, text, InlineKeyboardMarkup([[InlineKeyboardButton(f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back'), callback_data=back)]]), parse_mode='HTML')

    if data.startswith('view_compare_city_'):
        city = utils.decode_city(data[len('view_compare_city_'):])
        if city:
            return await _weather(query, context, city, lang, region, is_admin, from_compare=True)
    if data == 'back_to_compare':
        cities = context.user_data.get('last_compare_cities')
        if not cities:
            return await _edit(query, context, 'Сравнение не найдено. Начните новое.' if lang == 'rus' else 'Comparison unavailable. Start again.')
        s = await storage.get_user_settings(context, user_id)
        async def do_compare():
            text, error = await asyncio.to_thread(compare_cities, cities[0], cities[1], lang, s)
            return await _edit(query, context, text if text else f'{CROSS} {error}', utils.create_compare_result_keyboard(*cities, lang, settings=s,
                saved=await favorites.compare_contains(storage.get_db(context), user_id, *cities)))
        return await _pending(query, lang, do_compare())
    if data == 'start_new_compare':
        context.user_data['compare_step'] = 1
        context.user_data.pop('compare_city_1', None)
        return await _edit(query, context, ui('compare_first',lang), InlineKeyboardMarkup([[InlineKeyboardButton(f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back'), callback_data='nav_back')]]), parse_mode='HTML')

    # Устаревшие кнопки старых сообщений. Поминутная функция удалена.
    if data.startswith('minutely_'):
        return await _edit(query, context, 'Поминутный прогноз больше не поддерживается.' if lang == 'rus' else 'Minutely forecast is no longer supported.')

    # Точные префиксы прежде общих, чтобы "завтра" не перехватывалось "дождём".
    if data.startswith('hourly_page_'):
        payload = data[len('hourly_page_'):]
        number, sep, rest = payload.partition('_')
        if sep and number.isdigit():
            city, fav, key, compare = await _source(rest, context, query, user_id)
            if city:
                return await messages.show_hourly_forecast(update, context, city, int(number), fav, key, back_to_compare=compare)
    if data.startswith('hourly_'):
        payload = data[len('hourly_'):]
        for prefix in ('today_', 'tomorrow_'):
            if payload.startswith(prefix):
                payload = payload[len(prefix):]
        city, fav, key, compare = await _source(payload, context, query, user_id)
        if city:
            return await _pending(query, lang, messages.show_hourly_forecast(update, context, city, 0, fav, key, back_to_compare=compare))
    for prefix, day_offset in (('rain_tomorrow_',1), ('rain_today_',0), ('rain_',0)):
        if data.startswith(prefix):
            city, fav, key, compare = await _source(data[len(prefix):], context, query, user_id)
            if city:
                return await (messages.show_rain_forecast(update, context, city, day_offset, fav, key, compare)
                              if prefix != 'rain_' else
                              _pending(query, lang, messages.show_rain_forecast(update, context, city, day_offset, fav, key, compare)))
            break
    if data.startswith('week_forecast_'):
        city, fav, key, compare = await _source(data[len('week_forecast_'):], context, query, user_id)
        if city:
            return await _pending(query, lang, messages.show_week_forecast(update, context, city, fav, key, compare))
    if data.startswith('day_forecast_'):
        payload = data[len('day_forecast_'):]
        if payload.startswith('@'):
            payload = utils.decode_city(payload)
        if payload:
            rest, sep, offset = payload.rpartition('_')
            if sep and offset.isdigit():
                city, fav, key, compare = await _source(rest, context, query, user_id)
                if city:
                    return await _pending(query, lang, messages.show_day_forecast(update, context, city, int(offset), fav, key, compare))
    if data.startswith('week_summary_tomorrow_'):
        city, fav, key, compare = await _source(data[len('week_summary_tomorrow_'):], context, query, user_id)
        if city:
            return await _pending(query, lang, messages.show_week_summary_tomorrow(update, context, city, fav, key, compare))
    if data.startswith('week_summary_'):
        city, fav, key, compare = await _source(data[len('week_summary_'):], context, query, user_id)
        if city:
            return await _pending(query, lang, messages.show_week_summary(update, context, city, fav, key, compare))
    if data.startswith('alerts_'):
        city, fav, key, compare = await _source(data[len('alerts_'):], context, query, user_id)
        if city:
            return await _pending(query, lang, messages.show_weather_alerts(update, context, city, fav, key, compare))

    if data == 'updates_menu':
        return await messages.show_updates_menu(update, context)
    if data.startswith('changelog_'):
        return await messages.show_changelog(update, context, data[len('changelog_'):])
    logger.warning('Неизвестная кнопка: %s', data[:50])
    return await _edit(query, context, 'Кнопка устарела. Откройте меню заново.' if lang == 'rus' else 'This button expired. Reopen the menu.')
