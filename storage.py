from datetime import datetime
import logging

logger = logging.getLogger(__name__)

from config.env import ADV_ACTIVATION_KEYS
import favorites


CITY_TRANSLATIONS = {
    'rus_to_eng': {
        'москва': 'Moscow', 'минск': 'Minsk', 'санкт-петербург': 'Saint Petersburg',
        'спб': 'Saint Petersburg', 'нью-йорк': 'New York', 'лондон': 'London',
        'париж': 'Paris', 'берлин': 'Berlin', 'токио': 'Tokyo', 'пекин': 'Beijing'
    },
    'eng_to_rus': {
        'moscow': 'Москва', 'minsk': 'Минск', 'saint petersburg': 'Санкт-Петербург',
        'new york': 'Нью-Йорк', 'london': 'Лондон', 'paris': 'Париж', 'berlin': 'Берлин',
        'tokyo': 'Токио', 'beijing': 'Пекин'
    }
}

def get_db(context):
    return context.bot_data.get('db')

def init_bot_data(context):
    pass

def validate_activation_key(key: str) -> str:
    return 'adv' if key.upper().strip() in ADV_ACTIVATION_KEYS else None


def translate_city(city_name: str, target_lang: str) -> str:
    if not city_name:
        return city_name
    if target_lang == 'eng':
        return CITY_TRANSLATIONS['rus_to_eng'].get(city_name.lower().strip(), city_name)
    else:
        return CITY_TRANSLATIONS['eng_to_rus'].get(city_name.lower().strip(), city_name)

def reset_user_input_states(context, user_id: int):
    keys_to_clear = ['awaiting_region_input', 'awaiting_region_from_settings', 'compare_step', 'compare_city_1', 'compare_first_identity', 'awaiting_activation_key', 'came_from_favorites', 'fav_safe_id', 'came_from_compare']
    for key in keys_to_clear:
        context.user_data.pop(key, None)

def convert_city_to_english(city_name: str) -> str:
    city_map = {'москва': 'Moscow', 'минск': 'Minsk', 'санкт-петербург': 'Saint Petersburg', 'спб': 'Saint Petersburg', 'нью-йорк': 'New York', 'лондон': 'London', 'париж': 'Paris', 'берлин': 'Berlin', 'токио': 'Tokyo', 'пекин': 'Beijing'}
    return city_map.get(city_name.lower().strip(), city_name)

def _city_key(city: str) -> str:
    name = (city or '').strip().casefold()
    # Одинаково распознаём «Москва» и «Moscow», включая обновления языка.
    return CITY_TRANSLATIONS['rus_to_eng'].get(name, name).strip().casefold()


async def is_city_in_favorites(context, user_id: int, city: str) -> bool:
    db = get_db(context)
    return await favorites.contains(db, user_id, city) if db else False


async def get_canonical_city(context, user_id: int, city: str) -> str:
    db = get_db(context)
    if not db:
        return city
    lang = await get_user_lang(context, user_id)
    return await favorites.canonical_name(db, user_id, city, lang)


async def register_user(context, user_id: int, username: str = None, first_name: str = None):
    db = get_db(context)
    if db: await db.register_user(user_id, username, first_name)

async def get_user_lang(context, user_id: int):
    db = get_db(context)
    return await db.get_user_lang(user_id) if db else 'rus'

async def set_user_lang(context, user_id: int, lang: str):
    db = get_db(context)
    if db: await db.set_user_setting(user_id, 'language', lang)

async def get_user_level(context, user_id: int):
    db = get_db(context)
    return await db.get_user_level(user_id) if db else 'free'

async def set_user_level(context, user_id: int, level: str):
    db = get_db(context)
    if db: await db.update_user_field(user_id, 'level', level)

async def get_user_region(context, user_id: int):
    db = get_db(context)
    return await db.get_user_region(user_id) if db else None

async def set_user_region(context, user_id: int, region: str):
    db = get_db(context)
    if db: await db.update_user_field(user_id, 'region', region)

async def get_user_favorites(context, user_id: int):
    db = get_db(context)
    if not db:
        return []
    lang = await get_user_lang(context, user_id)
    return await favorites.list_names(db, user_id, lang)

async def add_user_favorite(context, user_id: int, city: str):
    db = get_db(context)
    return await favorites.add(db, user_id, city) if db else False

async def remove_user_favorite(context, user_id: int, city: str):
    db = get_db(context)
    return await favorites.remove(db, user_id, city) if db else False

async def clear_user_favorites(context, user_id: int):
    db = get_db(context)
    if db:
        await favorites.clear(db, user_id)

async def get_user_settings(context, user_id: int):
    db = get_db(context)
    return await db.get_user_settings(user_id) if db else {}

async def set_user_setting(context, user_id: int, key: str, value):
    db = get_db(context)
    if db: await db.set_user_setting(user_id, key, value)

async def get_all_users(context):
    db = get_db(context)
    return await db.get_all_users() if db else {}

async def get_temperature_unit(context, user_id: int) -> str:
    settings = await get_user_settings(context, user_id)
    return settings.get('temperature', 'celsius')

async def get_api_units(context, user_id: int) -> str:
    unit = await get_temperature_unit(context, user_id)
    return 'imperial' if unit == 'fahrenheit' else 'metric'

async def get_user_comparisons(context, user_id: int):
    db = get_db(context)
    lang = await get_user_lang(context, user_id)
    return await favorites.compare_list_pairs(db, user_id, lang)


async def add_user_comparison(context, user_id: int, first: str, second: str):
    return await favorites.compare_add(get_db(context), user_id, first, second)


async def remove_user_comparison(context, user_id: int, index: int):
    return await favorites.compare_remove(get_db(context), user_id, index)


async def remove_user_comparison_pair(context, user_id: int, first: str, second: str):
    return await favorites.compare_remove_pair(get_db(context), user_id, first, second)


async def clear_user_comparisons(context, user_id: int):
    await favorites.compare_clear(get_db(context), user_id)
