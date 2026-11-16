"""Сравнение двух городов: ровно два источника прогноза 1day, общий кэш 30 минут."""
from weather_api import get_daily_forecast, get_coordinates, get_weather_data
from weather_format import temperature, effective_settings
from config.texts import ui
from config.emojis import CROSS
import asyncio
import storage
import favorites
import utils
from config.emojis import (
    ICON_SUN_DAY, ICON_PARTLY_CLOUDY_DAY, CHECK, CLOUDS,
    RAIN, ICON_STORM, ICON_SNOW, ICON_FOG
)


def get_weather_icon(desc: str) -> str:
    text = (desc or '').lower()
    if any(x in text for x in ('thunder','гроза')):
        return ICON_STORM
    if any(x in text for x in ('rain','дожд', 'drizzle','морось')):
        return RAIN
    if any(x in text for x in ('snow','снег')):
        return ICON_SNOW
    if any(x in text for x in ('fog','туман','mist','дымка')):
        return ICON_FOG
    if any(x in text for x in ('few clouds', 'небольшая облачность', 'scattered')):
        return ICON_PARTLY_CLOUDY_DAY
    if any(x in text for x in ('cloud', 'облач', 'пасмур')):
        return CLOUDS
    return ICON_SUN_DAY


def compare_cities(city1: str, city2: str, lang='rus', settings=None, coords1=None, coords2=None):
    try:
        lat1, lon1 = coords1 if coords1 is not None else get_coordinates(city1)
        lat2, lon2 = coords2 if coords2 is not None else get_coordinates(city2)
        if lat1 is None or lat2 is None:
            return None, 'Не удалось найти города' if lang == 'rus' else 'Cities not found'
        # Оба платных запроса кэшируются по координатам; дополнительные вызовы не нужны.
        one = get_daily_forecast(lat1, lon1, 0, 5, lang)
        two = get_daily_forecast(lat2, lon2, 0, 5, lang)
        if not one or not two:
            return None, 'Прогноз временно недоступен' if lang == 'rus' else 'Forecast unavailable'
        s = effective_settings(settings)
        pairs = {day['local_date']: day for day in two}
        lines = [f'{CHECK} {city1} vs {city2}', '']
        for day in one:
            other = pairs.get(day['local_date'])
            if not other:
                continue
            lines.append(f"{day['day_short']} ({day['date']}): "
                f"{temperature(day['temp_day'], s, 1)} {get_weather_icon(day['desc'])} / "
                f"{temperature(other['temp_day'], s, 1)} {get_weather_icon(other['desc'])}")
        if len(lines) == 2:
            return None, 'Нет общих дат для сравнения' if lang == 'rus' else 'No overlapping dates'
        return '\n'.join(lines), None
    except Exception:
        return None, 'Не удалось сравнить города' if lang == 'rus' else 'Unable to compare cities'


async def start_compare(update, context):
    user_id = update.effective_user.id
    lang = await storage.get_user_lang(context, user_id)
    context.user_data['compare_step'] = 1
    context.user_data.pop('compare_city_1', None)
    context.user_data.pop('compare_first_identity', None)
    await update.message.reply_text(ui('compare_first',lang), parse_mode='HTML')


async def handle_compare_input(update, context, text, lang):
    """Обрабатывает только активный ввод пары городов. True = сообщение принято."""
    step = context.user_data.get('compare_step', 0)
    if step not in (1, 2):
        return False
    user_id = update.effective_user.id
    settings = await storage.get_user_settings(context, user_id)
    units = await storage.get_api_units(context, user_id)
    info, _ = await asyncio.to_thread(get_weather_data, text, lang, units, settings)
    if not info:
        await update.message.reply_text(ui('compare_invalid',lang,city=text))
        return True
    if step == 1:
        context.user_data['compare_city_1'] = info['city']
        context.user_data['compare_first_identity'] = info.get('identity')
        context.user_data['compare_step'] = 2
        await update.message.reply_text(ui('compare_second',lang))
        return True
    first = context.user_data.get('compare_city_1')
    second = info['city']
    if (context.user_data.get('compare_first_identity') and
            context.user_data['compare_first_identity'] == info.get('identity')) or first.casefold() == second.casefold():
        await update.message.reply_text(ui('compare_same',lang))
        return True
    context.user_data['last_compare_cities'] = [first, second]
    context.user_data['compare_step'] = 0
    context.user_data.pop('compare_city_1', None)
    context.user_data.pop('compare_first_identity', None)
    wait_msg = await update.message.reply_text(ui('processing',lang))
    try:
        result, error = await asyncio.to_thread(compare_cities, first, second, lang, settings)
    finally:
        try:
            await wait_msg.delete()
        except Exception:
            pass
    if result:
        saved = await favorites.compare_contains(storage.get_db(context), user_id, first, second)
        sent = await update.message.reply_text(result, reply_markup=utils.create_compare_result_keyboard(
            first, second, lang, settings=settings, saved=saved))
        context.user_data.setdefault('compare_by_message', {})[sent.message_id] = [first, second]
    else:
        await update.message.reply_text(f'{CROSS} {error}')
    return True
