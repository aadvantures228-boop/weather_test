from handlers import navigation
import logging
import asyncio
from html import escape
from datetime import datetime, timedelta
from weather_format import temperature, pressure as format_pressure, wind as format_wind, wind_direction, format_time, local_timezone, local_datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext
from telegram.error import BadRequest
import storage
import utils
from weather_api import (
    get_weather_data, get_hourly_forecast,
    get_daily_forecast, get_rain_forecast, get_city_details, get_coordinates,
    get_extended_hourly_forecast, same_city,
    is_russian_city, get_weather_alerts
)
from handlers.features.compare import handle_compare_input, compare_cities
from handlers import commands, admin
from config.emojis import *
from config.env import ADMIN_ID
from config.texts import ui, changelog
from weather_format import build_intervals, render_intervals

logger = logging.getLogger(__name__)
async def _safe_edit(query, context, text, reply_markup=None):
    try:
        await navigation.edit(query, context, text, reply_markup=reply_markup)
    except BadRequest as exc:
        if 'not modified' not in str(exc).lower():
            logger.warning('Не удалось обновить меню: %s', type(exc).__name__)


def _source_key(city, from_favorites=False, safe_id=None, back_to_compare=False):
    if from_favorites and safe_id:
        return safe_id
    return ('cmp_' if back_to_compare else '') + city


def _back_buttons(city, lang, from_favorites=False, safe_id=None, back_to_compare=False):
    if from_favorites and safe_id:
        cb = f'weather_fav_{safe_id}'
    elif back_to_compare:
        cb = 'back_to_compare'
    else:
        cb = utils.city_callback('weather_', city)
    return [[InlineKeyboardButton(f'{BACK} ' + ('Назад к погоде' if lang == 'rus' else 'Back to weather'), callback_data=cb)]]


def _back_keyboard(city, lang, from_favorites=False, safe_id=None, back_to_compare=False):
    return InlineKeyboardMarkup(_back_buttons(city, lang, from_favorites, safe_id, back_to_compare))


def _city_page(prefix, page, key, from_favorites=False, back_to_compare=False):
    if from_favorites:
        return f'{prefix}{page}_{key}'
    return utils.city_callback(f'{prefix}{page}_', key)


def _render_hourly_page(items, lang: str, settings: dict):
    """Первые 20 часов выводим подробно, далее объединяем подряд идущие 3-часовые осадки."""
    lines, date_now = [], None
    pending = None

    def fmt_time(dt):
        return dt.strftime('%I:%M %p').lstrip('0') if settings.get('time_format') == '12h' else dt.strftime('%H:%M')

    def event_kind(item):
        rain = float(item.get('rain') or 0)
        snow = float(item.get('snow') or 0)
        desc = str(item.get('desc') or '').casefold()
        if rain > 0 and snow > 0:
            return 'mixed', rain + snow
        if snow > 0:
            return 'snow', snow
        if rain > 0:
            return 'rain', rain
        if 'гроз' in desc or 'thunder' in desc:
            return 'thunder', 0.0
        return None, 0.0

    def event_label(kind, amount):
        if lang == 'rus':
            names = {'rain': 'дождь', 'snow': 'снег', 'mixed': 'дождь со снегом', 'thunder': 'гроза'}
            suffix = '' if kind == 'thunder' else f' {amount:.1f} мм'
        else:
            names = {'rain': 'rain', 'snow': 'snow', 'mixed': 'rain and snow', 'thunder': 'thunderstorm'}
            suffix = '' if kind == 'thunder' else f' {amount:.1f} mm'
        return names[kind] + suffix

    def flush_pending():
        nonlocal pending
        if not pending:
            return
        start = fmt_time(pending['start'])
        end = fmt_time(pending['end'])
        lines.append(f"{start}–{end} — {event_label(pending['kind'], pending['amount'])}")
        pending = None

    for item in items:
        dt = item['datetime']
        if date_now != dt.date():
            flush_pending()
            date_now = dt.date()
            lines.append(f'\n{date_now:%d.%m}:')
        kind, amount = event_kind(item)
        if item.get('step_hours') == 3 and kind:
            start = item.get('interval_start') or (dt - timedelta(hours=3))
            if pending and pending['kind'] == kind and start <= pending['end']:
                pending['end'] = dt
                pending['amount'] += amount
            else:
                flush_pending()
                pending = {'kind': kind, 'start': start, 'end': dt, 'amount': amount}
            continue
        flush_pending()
        t = fmt_time(dt)
        lines.append(f"{t} — {temperature(item['temp'], settings, 1)} — {item['desc']}")
    flush_pending()
    return lines


async def handle_reply(update: Update, context: CallbackContext):
    text = update.message.text.strip() if update.message.text else ""
    user_id = update.effective_user.id
    lang = await storage.get_user_lang(context, user_id)
    current_region = await storage.get_user_region(context, user_id)
    
    # Импортируем ADMIN_ID напрямую из config.env
    from config.env import ADMIN_ID
    is_admin = (user_id == ADMIN_ID)

    await storage.register_user(context, user_id,
                         update.effective_user.username,
                         update.effective_user.first_name)

    # Личное сообщение или повышение из карточки пользователя (без ввода ID).
    if await admin.handle_direct_input(update, context, text, lang):
        return

    # Старые сценарии рассылки перенесены в админ-модуль; кнопки Beta 1.1 сохранены.
    if await admin.handle_legacy_admin_input(update, context, text, lang):
        return

    # Обработка активационного ключа
    if context.user_data.get('awaiting_activation_key', False):
        if text.lower() == "/cancel":
            context.user_data['awaiting_activation_key'] = False
            await update.message.reply_text(
                f"{CROSS} Активация отменена." if lang == "rus" else f"{CROSS} Activation cancelled."
            )
            return
        
        key_level = storage.validate_activation_key(text)
        if key_level:
            await storage.set_user_level(context, user_id, key_level)
            context.user_data['awaiting_activation_key'] = False
            msg = (f"{CHECK} Уровень '{key_level.upper()}' активирован! "
                   f"Расширенные функции доступны." if lang == "rus" else
                   f"{CHECK} Level '{key_level.upper()}' activated! "
                   f"Extended features available.")
            await update.message.reply_text(msg)
        else:
            msg = (f"{CROSS} Неверный ключ активации." if lang == "rus" else
                   f"{CROSS} Invalid activation key.")
            await update.message.reply_text(msg)
        return

    # ОБРАБОТКА /cancel
    if text == "/cancel":
        context.user_data['compare_step'] = 0
        context.user_data['awaiting_region_input'] = False
        context.user_data['awaiting_region_from_settings'] = False
        context.user_data.pop('compare_city_1', None)
        context.user_data['awaiting_activation_key'] = False
        context.user_data.pop('came_from_favorites', None)
        context.user_data.pop('fav_safe_id', None)
        context.user_data.pop('came_from_compare', None)
        for key in ('admin_awaiting_broadcast', 'admin_awaiting_user_id', 'admin_awaiting_user_message'):
            if context.bot_data.get(key) == user_id:
                context.bot_data.pop(key, None)
        await update.message.reply_text(
            f"{CROSS} Все процессы отменены." if lang == "rus" else f"{CROSS} All processes cancelled."
        )
        return

    # Команда "k" для активации
    if text.lower() == "k":
        context.user_data['awaiting_activation_key'] = True
        msg = ui('activation_prompt',lang)
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    menu_buttons = utils.get_main_menu_buttons(lang, is_admin)

    # НАЖАТИЕ КНОПКИ МЕНЮ
    if text in menu_buttons:
        context.user_data['compare_step'] = 0
        context.user_data['awaiting_region_input'] = False
        context.user_data['awaiting_region_from_settings'] = False
        context.user_data.pop('compare_city_1', None)
        context.user_data['awaiting_activation_key'] = False
        context.user_data.pop('came_from_favorites', None)
        context.user_data.pop('fav_safe_id', None)
        context.user_data.pop('came_from_compare', None)

        if text == f"{SETTINGS} Настройки" or text == f"{SETTINGS} Settings":
            return await commands.settings(update, context)
        elif text == f"{FAVORITES} Избранное" or text == f"{FAVORITES} Favorites":
            return await favorites(update, context)
        elif text == f"{SUNRISE} Погода в моем регионе" or text == f"{SUNRISE} Weather in my region":
            return await get_weather_for_region(update, context)
        elif text == f"{UPDATES} Обновления" or text == f"{UPDATES} Updates":
            return await show_updates_menu(update, context)
        elif text == f"{COMPARE} Сравнить" or text == f"{COMPARE} Compare":
            return await commands.compare(update, context)
        elif is_admin and (text == f"{ADMIN} Админ-панель" or text == f"{ADMIN} Admin panel"):
            return await admin.admin_panel(update, context)

    # Сценарий сравнения расположен в features/compare.py.
    if await handle_compare_input(update, context, text, lang):
        return

    if context.user_data.get('awaiting_region_input') or context.user_data.get('awaiting_region_from_settings'):
        api_units = await storage.get_api_units(context, user_id)
        weather_info, weather_text = await asyncio.to_thread(get_weather_data, text, lang, api_units, await storage.get_user_settings(context, user_id))
        if weather_info:
            city = weather_info.get('city', text)
            await storage.set_user_region(context, user_id, city)
            context.user_data['awaiting_region_input'] = False
            context.user_data['awaiting_region_from_settings'] = False
            # Регион только что выбран: кнопка повторной установки здесь не нужна.
            # Копия словаря не меняет сохранённые настройки пользователя.
            user_settings = dict(await storage.get_user_settings(context, user_id) or {})
            user_settings['show_set_region_btn'] = False
            await update.message.reply_text(
                weather_text,
                reply_markup=utils.create_weather_keyboard(
                    city,
                    await storage.is_city_in_favorites(context, user_id, city),
                    city,
                    lang,
                    is_admin=is_admin,
                    settings=user_settings,
                    is_current_region=True
                )
            )
        else:
            await update.message.reply_text(
                f"{CROSS} Город «{text}» не найден. Попробуйте еще раз или нажмите /cancel:"
                if lang == "rus" else
                f"{CROSS} City «{text}» not found. Try again or press /cancel:"
            )
        return

    api_units = await storage.get_api_units(context, user_id)
    weather_info, weather_text = await asyncio.to_thread(get_weather_data, text, lang, api_units, await storage.get_user_settings(context, user_id))
    if weather_info:
        city = weather_info.get('city', text)
        user_settings = await storage.get_user_settings(context, user_id)
        await update.message.reply_text(
            weather_text,
            reply_markup=utils.create_weather_keyboard(
                city,
                await storage.is_city_in_favorites(context, user_id, city),
                current_region,
                lang,
                is_admin=is_admin,
                settings=user_settings,
                is_current_region=bool(current_region and (city.casefold() == current_region.casefold() or
                    await asyncio.to_thread(same_city, city, current_region)))
            )
        )
    else:
        await update.message.reply_text(weather_text)
async def get_weather_for_region(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    lang = await storage.get_user_lang(context, user_id)
    region = await storage.get_user_region(context, user_id)
    is_admin = (user_id == ADMIN_ID)

    if not region:
        context.user_data['awaiting_region_input'] = True
        await update.message.reply_text(
            f"{LOCATION} Вы еще не выбрали свой регион!\n\n"
            f"Введите название города прямо в чат, и он автоматически станет вашим регионом."
            if lang == "rus" else
            f"{LOCATION} You haven't selected your region yet!\n\n"
            f"Enter the city name directly in the chat, and it will automatically become your region."
        )
        return

    api_units = await storage.get_api_units(context, user_id)
    weather_info, weather_text = await asyncio.to_thread(get_weather_data, region, lang, api_units, await storage.get_user_settings(context, user_id))
    if weather_info:
        city = weather_info.get('city', region)
        # При просмотре своего региона кнопка «Сделать моим регионом» не нужна.
        user_settings = dict(await storage.get_user_settings(context, user_id) or {})
        user_settings['show_set_region_btn'] = False
        await update.message.reply_text(
            weather_text,
            reply_markup=utils.create_weather_keyboard(
                city,
                await storage.is_city_in_favorites(context, user_id, city),
                region,
                lang,
                is_admin=is_admin,
                settings=user_settings,
                is_current_region=bool(region and (city.casefold() == region.casefold() or
                    await asyncio.to_thread(same_city, city, region)))
            )
        )
    else:
        await update.message.reply_text(
            f"{CROSS} Не удалось получить погоду для региона {region}"
            if lang == "rus" else
            f"{CROSS} Failed to get weather for region {region}"
        )

async def favorites(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = update.effective_user.id
    lang = await storage.get_user_lang(context, user_id)
    fav_list = await storage.get_user_favorites(context, user_id)
    pairs = await storage.get_user_comparisons(context, user_id)
    settings = await storage.get_user_settings(context, user_id)
    if not fav_list and not pairs:
        text = (f'{FAVORITES} Ваш список избранного пуст.' if lang == 'rus'
                else f'{FAVORITES} Your favorites list is empty.')
        if update.message:
            await update.message.reply_text(text)
        else:
            await _safe_edit(query, context, text, reply_markup=InlineKeyboardMarkup([]))
        return

    semaphore = asyncio.Semaphore(5)
    async def weather_for(city):
        async with semaphore:
            return await asyncio.to_thread(get_weather_data, city, lang, 'metric', settings)
    weather = await asyncio.gather(*(weather_for(c) for c in fav_list), return_exceptions=True)
    header = (f'{FAVORITES} Ваше избранное:' if lang == 'rus'
              else f'{FAVORITES} Your favorites:')
    keyboard, fav_map = [], {}
    for idx, (city, answer) in enumerate(zip(fav_list, weather)):
        safe_id = f'fav_{idx}'
        fav_map[safe_id] = city
        w_info = answer[0] if isinstance(answer, tuple) else None
        temp_text = temperature(w_info.get('temp'), settings, 0) if w_info else '—'
        keyboard.append([
            InlineKeyboardButton(f'{CITY} {city} ({temp_text})', callback_data=f'weather_fav_{safe_id}'),
            InlineKeyboardButton(CROSS, callback_data=f'remove_favorite_{safe_id}')
        ])
    for pair in pairs:
        idx = pair['index']
        label = f"{COMPARE} {pair['first']} — {pair['second']}"
        keyboard.append([
            InlineKeyboardButton(label[:64], callback_data=f'favorite_compare_{idx}'),
            InlineKeyboardButton(CROSS, callback_data=f'remove_compare_{idx}')
        ])
    keyboard.append([InlineKeyboardButton(f'{TRASH} ' + ('Очистить весь список' if lang == 'rus'
                      else 'Clear all favorites'), callback_data='clear_all_favorites')])
    if query:
        keyboard.append([InlineKeyboardButton(f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back'), callback_data='nav_back')])
    markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        sent = await update.message.reply_text(header, reply_markup=markup)
        msg_id = sent.message_id
    else:
        await _safe_edit(query, context, header, reply_markup=markup)
        msg_id = query.message.message_id
    context.user_data.setdefault('fav_maps_by_message', {})[msg_id] = fav_map
    context.user_data['fav_map'] = fav_map









async def show_hourly_forecast(update: Update, context: CallbackContext, city_name: str,
                               page: int=0, from_favorites: bool=False, safe_id: str=None,
                               force_refresh: bool=False, back_to_compare: bool=False):
    query = update.callback_query
    lang = await storage.get_user_lang(context, query.from_user.id)
    settings = await storage.get_user_settings(context, query.from_user.id)
    lat, lon = await asyncio.to_thread(get_coordinates, city_name)
    if lat is None:
        return await _safe_edit(query, context, f'{WARNING} ' + ('Город не найден' if lang == 'rus' else 'City not found'))
    forecast = await asyncio.to_thread(get_extended_hourly_forecast, lat, lon, 0, lang)
    if not forecast:
        return await _safe_edit(query, context,
            f'{WARNING} ' + ('Прогноз временно недоступен' if lang == 'rus' else 'Forecast unavailable'),
            reply_markup=_back_keyboard(city_name, lang, from_favorites, safe_id, back_to_compare))
    chunks = [forecast[i:i+12] for i in range(0, len(forecast), 12)]
    page = max(0, min(int(page), len(chunks)-1))
    lines = _render_hourly_page(chunks[page], lang, settings)
    label = 'Прогноз по часам и на 5 дней' if lang == 'rus' else 'Hourly and 5-day forecast'
    text = f'{HOURLY} {label} ({city_name}) — {page+1}/{len(chunks)}:\n' + '\n'.join(lines)
    if any(h.get('step_hours') == 3 for h in chunks[page]):
        text += ('\n\n(далее через каждые 3 часа)' if lang == 'rus'
                 else '\n\n(next every 3 hours)')
    key = _source_key(city_name, from_favorites, safe_id, back_to_compare)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back'),
                    callback_data=_city_page('hourly_page_', page-1, key, from_favorites, back_to_compare)))
    if page + 1 < len(chunks):
        nav.append(InlineKeyboardButton(('Вперёд ' if lang == 'rus' else 'Next ') + RIGHT_ARROW,
                    callback_data=_city_page('hourly_page_', page+1, key, from_favorites, back_to_compare)))
    buttons = [nav] if nav else []
    buttons += _back_buttons(city_name, lang, from_favorites, safe_id, back_to_compare)
    await _safe_edit(query, context, text, reply_markup=InlineKeyboardMarkup(buttons))


async def show_rain_forecast(update: Update, context: CallbackContext, city_name: str,
                             day_offset: int=0, from_favorites: bool=False, safe_id: str=None,
                             back_to_compare: bool=False):
    query = update.callback_query
    lang = await storage.get_user_lang(context, query.from_user.id)
    settings = await storage.get_user_settings(context, query.from_user.id)
    lat, lon = await asyncio.to_thread(get_coordinates, city_name)
    if lat is None:
        return await _safe_edit(query, context, f'{WARNING} ' + ('Город не найден' if lang == 'rus' else 'City not found'))
    hours = await asyncio.to_thread(get_extended_hourly_forecast, lat, lon, 0, lang)
    if not hours:
        return await _safe_edit(query, context,
            f'{WARNING} ' + ('Прогноз временно недоступен' if lang == 'rus' else 'Forecast unavailable'),
            reply_markup=_back_keyboard(city_name, lang, from_favorites, safe_id, back_to_compare))
    tz = hours[0]['datetime'].tzinfo
    target_day = datetime.now(tz).date() + timedelta(days=day_offset)
    groups = build_intervals(hours, target_day)
    details = render_intervals(groups, lang, settings.get('time_format', '24h'))
    label = ('сегодня' if day_offset == 0 else 'завтра') if lang == 'rus' else ('today' if day_offset == 0 else 'tomorrow')
    title = f'{RAIN} ' + (f'Осадки на {label} ({city_name}):' if lang == 'rus'
                        else f'Precipitation for {label} ({city_name}):')
    key = _source_key(city_name, from_favorites, safe_id, back_to_compare)
    next_day = 1 if day_offset == 0 else 0
    prefix = f'rain_{"tomorrow" if next_day else "today"}_'
    cb = f'{prefix}{key}' if from_favorites else utils.city_callback(prefix, ('cmp_' if back_to_compare else '') + city_name)
    toggle_label = ((('Завтра ' + RIGHT_ARROW) if lang == 'rus' else ('Tomorrow ' + RIGHT_ARROW))
                    if day_offset == 0 else
                    ((BACK + ' Сегодня') if lang == 'rus' else (BACK + ' Today')))
    buttons = [[InlineKeyboardButton(toggle_label, callback_data=cb)]]
    alerts_cb = f'alerts_{key}' if from_favorites else utils.city_callback('alerts_', ('cmp_' if back_to_compare else '')+city_name)
    buttons.append([InlineKeyboardButton(f'{WARNING} ' + ('Штормовые предупреждения' if lang == 'rus' else 'Storm warnings'), callback_data=alerts_cb)])
    buttons += _back_buttons(city_name, lang, from_favorites, safe_id, back_to_compare)
    await _safe_edit(query, context, f'{title}\n\n{details}', reply_markup=InlineKeyboardMarkup(buttons))






async def show_weather_alerts(update: Update, context: CallbackContext, city_name: str,
                              from_favorites: bool=False, safe_id: str=None, back_to_compare: bool=False):
    """Предупреждения для всех пользователей, общий 30-минутный кэш API."""
    query = update.callback_query
    lang = await storage.get_user_lang(context, query.from_user.id)
    lat, lon = await asyncio.to_thread(get_coordinates, city_name)
    if lat is None:
        text = f'{WARNING} ' + ('Город не найден' if lang == 'rus' else 'City not found')
    else:
        alerts = await asyncio.to_thread(get_weather_alerts, lat, lon, lang)
        if alerts is None:
            text = f'{WARNING} ' + ('Не удалось получить подробности предупреждений. Попробуйте позже.'
                                   if lang == 'rus' else 'Could not load weather alert details. Try later.')
        elif not alerts:
            text = f'{WARNING} ' + (f'Действующих штормовых предупреждений для {city_name} нет.'
                                   if lang == 'rus' else f'No active storm warnings for {city_name}.')
        else:
            text = f'{WARNING} ' + (f'Штормовые предупреждения для {city_name}:'
                                   if lang == 'rus' else f'Weather alerts for {city_name}:')
            for alert in alerts:
                def label_time(value):
                    if value is None:
                        return 'Н/Д' if lang == 'rus' else 'N/A'
                    try:
                        return local_datetime(value, alert.get('timezone_offset'),
                                              alert.get('timezone_name')).strftime('%d.%m.%Y %H:%M')
                    except (ValueError, TypeError, OverflowError):
                        return 'Н/Д' if lang == 'rus' else 'N/A'
                # Telegram ограничивает сообщение 4096 символами; не выводим голые ID.
                title = str(alert.get('event') or ('Предупреждение' if lang == 'rus' else 'Alert'))
                agency = str(alert.get('sender_name') or '—')
                description = str(alert.get('description') or
                    ('Описание не предоставлено метеослужбой.' if lang == 'rus' else 'No details provided by the agency.'))
                description = description[:1200] + ('…' if len(description) > 1200 else '')
                block = (f'\n\n{WARNING} {title}\n' +
                         (f'От: {agency}\n' if lang == 'rus' else f'From: {agency}\n') +
                         f'{label_time(alert.get("start"))} — {label_time(alert.get("end"))}\n'
                         f'{description}')
                if len(text) + len(block) > 3600:
                    text += '\n\n…' if lang == 'rus' else '\n\n…'
                    break
                text += block
    await _safe_edit(query, context, text,
                     reply_markup=_back_keyboard(city_name, lang, from_favorites, safe_id, back_to_compare))



async def show_week_forecast(update: Update, context: CallbackContext, city_name: str,
                             from_favorites: bool=False, safe_id: str=None, back_to_compare: bool=False):
    query = update.callback_query
    lang = await storage.get_user_lang(context, query.from_user.id)
    settings = await storage.get_user_settings(context, query.from_user.id)
    lat, lon = await asyncio.to_thread(get_coordinates, city_name)
    if lat is None:
        await _safe_edit(query, context, f'{WARNING} ' + ('Город не найден' if lang == 'rus' else 'City not found'))
        return
    forecast = await asyncio.to_thread(get_daily_forecast, lat, lon, 0, 8, lang)
    if not forecast:
        await _safe_edit(query, context, f'{WARNING} ' + ('Нет данных прогноза' if lang == 'rus' else 'Forecast unavailable'),
                         reply_markup=_back_keyboard(city_name, lang, from_favorites, safe_id, back_to_compare))
        return
    now_day = datetime.now(local_timezone(forecast[0]['timezone_offset'], forecast[0]['timezone_name'])).date()
    # Только будущие даты; не выдаём сегодняшний день под названием «завтра».
    options = [(i, d) for i, d in enumerate(forecast) if d['local_date'] > now_day][:7]
    if not options:
        options = list(enumerate(forecast[:7]))
    text = f'{WEEKLY_FORECAST} ' + (f'Прогноз в {city_name}:\nВыберите день:' if lang == 'rus' else f'Forecast for {city_name}:\nChoose a day:')
    keyboard = []
    key = _source_key(city_name, from_favorites, safe_id, back_to_compare)
    for i, d in options:
        if from_favorites:
            cb = f'day_forecast_{safe_id}_{i}'
        else:
            cb = utils.city_callback('day_forecast_', ('cmp_' if back_to_compare else '')+city_name + f'_{i}')
        label = (('Завтра' if lang == 'rus' else 'Tomorrow') if d['local_date'] == now_day + timedelta(days=1) else d['day_short'])
        button = InlineKeyboardButton(f"{label} ({d['date']}) {temperature(d['temp_day'], settings, 1)}", callback_data=cb)
        if len(keyboard) and len(keyboard[-1]) == 1 and label not in ('Завтра','Tomorrow'):
            keyboard[-1].append(button)
        else:
            keyboard.append([button])
    summary_cb = f'week_summary_{key}' if from_favorites else utils.city_callback('week_summary_', ('cmp_' if back_to_compare else '')+city_name)
    keyboard.append([InlineKeyboardButton(f'{PRESSURE} ' + ('Сводка на неделю' if lang == 'rus' else 'Weekly summary'), callback_data=summary_cb)])
    keyboard += _back_buttons(city_name, lang, from_favorites, safe_id, back_to_compare)
    await _safe_edit(query, context, text, reply_markup=InlineKeyboardMarkup(keyboard))




async def show_day_forecast(update: Update, context: CallbackContext, city_name: str,
                            day_offset: int, from_favorites: bool=False, safe_id: str=None, back_to_compare: bool=False):
    query = update.callback_query
    lang = await storage.get_user_lang(context, query.from_user.id)
    s = await storage.get_user_settings(context, query.from_user.id)
    lat, lon = await asyncio.to_thread(get_coordinates, city_name)
    if lat is None:
        await _safe_edit(query, context, f'{WARNING} ' + ('Город не найден' if lang == 'rus' else 'City not found'))
        return
    forecast = await asyncio.to_thread(get_daily_forecast, lat, lon, 0, 8, lang)
    if not forecast or not 0 <= int(day_offset) < len(forecast):
        text = f'{WARNING} ' + ('Нет данных' if lang == 'rus' else 'No data')
    else:
        d = forecast[int(day_offset)]
        now_day = datetime.now(local_timezone(d['timezone_offset'], d['timezone_name'])).date()
        label = ('завтра' if lang == 'rus' else 'tomorrow') if d['local_date'] == now_day+timedelta(days=1) else d['day_full']
        lines = [f'{WEEKLY_FORECAST} ' + (f'Погода в {city_name} на {label} ({d["date_full"]}):' if lang == 'rus' else f'Weather in {city_name} on {label} ({d["date_full"]}):'),
                 f'{DESCRIPTION} {d["desc"]}',
                 f'{THERMOMETER} ' + ('Температура' if lang == 'rus' else 'Temperature') + f": {temperature(d['temp_day'], s, 1)} ({'ощущается' if lang == 'rus' else 'feels like'} {temperature(d['feels_like'],s,1)})",
                 f'{PRESSURE} ' + ('Диапазон' if lang == 'rus' else 'Range') + f": {temperature(d['temp_min'],s,1)} – {temperature(d['temp_max'],s,1)}",
                 f'{HUMIDITY} ' + ('Влажность' if lang == 'rus' else 'Humidity') + f": {d['humidity'] if d['humidity'] is not None else '—'}%",
                 f'{PRESSURE} ' + ('Давление' if lang == 'rus' else 'Pressure') + f": {format_pressure(d['pressure'],s,lang)}",
                 f'{WIND} ' + ('Ветер' if lang == 'rus' else 'Wind') + f": {format_wind(d['wind_speed'],s,lang)}"]
        if s.get('show_clouds', True) and d.get('clouds') is not None:
            lines.append(f'{CLOUDS} ' + ('Облачность' if lang == 'rus' else 'Clouds') + f": {d['clouds']}%")
        if s.get('show_wind_direction',True) and d.get('wind_deg') is not None:
            lines.append(f'{WIND} ' + ('Направление' if lang == 'rus' else 'Direction') + f": {wind_direction(d['wind_deg'],lang)}")
        if s.get('show_wind_gust',True) and d.get('wind_gust') is not None:
            lines.append(f'{WIND} ' + ('Порывы' if lang == 'rus' else 'Gusts') + f": {format_wind(d['wind_gust'],s,lang)}")
        if s.get('show_sunrise_sunset',True):
            lines.append(f"{SUNRISE} {'Восход' if lang == 'rus' else 'Sunrise'}: {format_time(d['sunrise'],s,d['timezone_offset'],d['timezone_name'])} | {SUNSET} {'Закат' if lang == 'rus' else 'Sunset'}: {format_time(d['sunset'],s,d['timezone_offset'],d['timezone_name'])}")
        text = '\n'.join(lines)
    key = _source_key(city_name, from_favorites, safe_id, back_to_compare)
    cb = f'week_forecast_{key}' if from_favorites else utils.city_callback('week_forecast_', ('cmp_' if back_to_compare else '')+city_name)
    await _safe_edit(query, context, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f'{BACK} ' + ('Назад к неделе' if lang == 'rus' else 'Back to week'),callback_data=cb)]]))




async def show_sunset_tomorrow(update: Update, context: CallbackContext, city_name: str):
    query = update.callback_query
    await query.answer("Эта функция устарела", show_alert=True)


async def show_week_summary(update: Update, context: CallbackContext, city_name: str,
                            from_favorites: bool=False, safe_id: str=None, back_to_compare: bool=False):
    query = update.callback_query
    lang = await storage.get_user_lang(context, query.from_user.id)
    s = await storage.get_user_settings(context, query.from_user.id)
    lat, lon = await asyncio.to_thread(get_coordinates, city_name)
    if lat is None:
        await _safe_edit(query, context, f'{WARNING} ' + ('Город не найден' if lang == 'rus' else 'City not found'))
        return
    forecast = await asyncio.to_thread(get_daily_forecast, lat, lon, 0, 8, lang)
    if not forecast:
        text = f'{WARNING} ' + ('Нет данных' if lang == 'rus' else 'No data')
    else:
        now_day = datetime.now(local_timezone(forecast[0]['timezone_offset'], forecast[0]['timezone_name'])).date()
        days = [d for d in forecast if d['local_date'] > now_day][:7]
        if not days:
            days = forecast[:7]
        lines = [f"{d['day_short']} ({d['date']}): {temperature(d['temp_min'],s,1)} – {temperature(d['temp_max'],s,1)} {d['desc']}" for d in days]
        text = f'{PRESSURE} ' + (f'Сводка на неделю ({city_name}):' if lang == 'rus' else f'Weekly summary ({city_name}):') + '\n\n' + '\n'.join(lines)
    key = _source_key(city_name, from_favorites, safe_id, back_to_compare)
    cb = f'week_forecast_{key}' if from_favorites else utils.city_callback('week_forecast_', ('cmp_' if back_to_compare else '')+city_name)
    await _safe_edit(query, context, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back'), callback_data=cb)]]))




async def show_week_summary_tomorrow(update: Update, context: CallbackContext, city_name: str,
                                     from_favorites: bool=False, safe_id: str=None, back_to_compare: bool=False):
    """Совместимость со старыми кнопками сводки на завтра."""
    query = update.callback_query
    lang = await storage.get_user_lang(context, query.from_user.id)
    s = await storage.get_user_settings(context, query.from_user.id)
    lat, lon = await asyncio.to_thread(get_coordinates, city_name)
    forecast = await asyncio.to_thread(get_daily_forecast, lat, lon, 0, 8, lang) if lat is not None else None
    tomorrow = None
    if forecast:
        date = datetime.now(local_timezone(forecast[0]['timezone_offset'], forecast[0]['timezone_name'])).date() + timedelta(days=1)
        tomorrow = next((d for d in forecast if d['local_date'] == date), None)
    if tomorrow:
        text = (f'{PRESSURE} ' + ('Завтра' if lang == 'rus' else 'Tomorrow') + f" ({city_name}):\n{temperature(tomorrow['temp_min'],s,1)} – {temperature(tomorrow['temp_max'],s,1)}\n{tomorrow['desc']}")
    else:
        text = f'{WARNING} ' + ('Нет данных на завтра' if lang == 'rus' else 'No forecast for tomorrow')
    key = _source_key(city_name, from_favorites, safe_id, back_to_compare)
    cb = f'week_forecast_{key}' if from_favorites else utils.city_callback('week_forecast_', ('cmp_' if back_to_compare else '')+city_name)
    await _safe_edit(query, context, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back'), callback_data=cb)]]))




async def show_updates_menu(update: Update, context: CallbackContext):
    query = update.callback_query if hasattr(update, 'callback_query') else None
    user_id = update.effective_user.id if update.message else query.from_user.id
    lang = await storage.get_user_lang(context, user_id)
    text = ui('settings_updates', lang)
    keyboard = [
        [InlineKeyboardButton(f'{BETA} Beta 1.0', callback_data='changelog_beta'),
         InlineKeyboardButton(f'{RELEASE} Release 1.0', callback_data='changelog_1_0')],
        [InlineKeyboardButton(f'{PATCH} 1.0.1', callback_data='changelog_1_0_1'),
         InlineKeyboardButton(f'{PATCH} 1.0.2', callback_data='changelog_1_0_2'),
         InlineKeyboardButton(f'{PATCH} 1.0.3', callback_data='changelog_1_0_3')],
        [InlineKeyboardButton(f'{BETA} Beta 1.1', callback_data='changelog_1_1'),
         InlineKeyboardButton(f'{RELEASE} Release 1.1', callback_data='changelog_release_1_1')],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode='HTML')
    else:
        await navigation.edit(query, context, text, reply_markup=markup, parse_mode='HTML')


async def show_changelog(update: Update, context: CallbackContext, version: str):
    query = update.callback_query
    lang = await storage.get_user_lang(context, query.from_user.id)
    back_label = f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back')
    keyboard = []
    if version == 'release_1_1':
        keyboard.append([
            InlineKeyboardButton(f'{PRE_RELEASE} Pre-release 1.1-1', callback_data='changelog_pre_1_1_1'),
            InlineKeyboardButton(f'{PRE_RELEASE} Pre-release 1.1-2', callback_data='changelog_pre_1_1_2')])
    parent = 'changelog_release_1_1' if version in ('pre_1_1_1', 'pre_1_1_2') else 'updates_menu'
    keyboard.append([InlineKeyboardButton(back_label, callback_data=parent)])
    await navigation.edit(query, context, changelog(version, lang),
                          reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
