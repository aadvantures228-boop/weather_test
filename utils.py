from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from config.emojis import *
import hashlib

# Короткие идентификаторы защищают callback_data от лимита Telegram (64 байта).
_CITY_CALLBACK_MAP = {}

def city_callback(prefix, city):
    value = city.replace(" ", "_")
    callback = f"{prefix}{value}"
    if len(callback.encode("utf-8")) <= 64:
        return callback
    key = "@" + hashlib.sha256(city.encode("utf-8")).hexdigest()[:16]
    _CITY_CALLBACK_MAP[key] = city
    return f"{prefix}{key}"

def decode_city(payload):
    if payload.startswith("@"):
        return _CITY_CALLBACK_MAP.get(payload)
    return payload.replace("_", " ")


def get_main_menu_buttons(lang: str, is_admin: bool = False) -> list:
    if lang == "eng":
        buttons = [
            f"{SETTINGS} Settings",
            f"{FAVORITES} Favorites",
            f"{SUNRISE} Weather in my region",
            f"{UPDATES} Updates",
            f"{COMPARE} Compare"
        ]
        if is_admin:
            buttons.append(f"{ADMIN} Admin panel")
        return buttons
    else:
        buttons = [
            f"{SETTINGS} Настройки",
            f"{FAVORITES} Избранное",
            f"{SUNRISE} Погода в моем регионе",
            f"{UPDATES} Обновления",
            f"{COMPARE} Сравнить"
        ]
        if is_admin:
            buttons.append(f"{ADMIN} Админ-панель")
        return buttons


def create_main_keyboard(user_id: int, admin_id: int, lang: str):
    is_admin = (user_id == admin_id)
    buttons = get_main_menu_buttons(lang, is_admin)
    
    keyboard = []
    if lang == "eng":
        keyboard = [
            [buttons[0], buttons[1]],
            [buttons[2], buttons[3]],
            [buttons[4]]
        ]
        if is_admin and len(buttons) > 5:
            keyboard.append([buttons[5]])
    else:
        keyboard = [
            [buttons[0], buttons[1]],
            [buttons[2], buttons[3]],
            [buttons[4]]
        ]
        if is_admin and len(buttons) > 5:
            keyboard.append([buttons[5]])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def create_weather_keyboard(city_name: str, city_in_favorites: bool, current_region: str, 
                            lang: str = "rus", from_favorites: bool = False, safe_id: str = None, 
                            back_to_compare: bool = False, is_admin: bool = False, settings: dict = None,
                            is_current_region: bool = None):
    if settings is None:
        settings = {}
    
    keyboard = []
    if is_current_region is None:
        is_current_region = city_name.casefold() == current_region.casefold() if current_region else False

    # Получаем настройки отображения
    show_extra_data_btn = settings.get('show_extra_data_btn', True)
    show_set_region_btn = settings.get('show_set_region_btn', True)
    
    # Первая строка: управление (только если НЕ из избранного и НЕ из сравнения)
    if not from_favorites and not back_to_compare:
        row = []
        # Кнопка "Сделать моим регионом" — проверяем настройку
        if not is_current_region and show_set_region_btn:
            row.append(InlineKeyboardButton(
                f"{LOCATION} Сделать моим регионом" if lang == "rus" else f"{LOCATION} Set as my region",
                callback_data=city_callback("set_region_", city_name)
            ))
        if city_in_favorites:
            row.append(InlineKeyboardButton(
                f"{CROSS} Удалить из избранного" if lang == "rus" else f"{CROSS} Remove from favorites",
                callback_data=city_callback("remove_favorite_", city_name)
            ))
        else:
            row.append(InlineKeyboardButton(
                f"{FAVORITES} Добавить в избранное" if lang == "rus" else f"{FAVORITES} Add to favorites",
                callback_data=city_callback("add_favorite_", city_name)
            ))
        if row:
            keyboard.append(row)
    
    # Прогнозы. Сохраняем источник перехода внутри callback, а не в глобальном флаге.
    if from_favorites and safe_id:
        hourly_cb = f'hourly_{safe_id}'
        rain_cb = f'rain_{safe_id}'
        week_cb = f'week_forecast_{safe_id}'
        extra_cb = f'extra_{safe_id}'
        refresh_cb = f'refresh_weather_{safe_id}'
    elif back_to_compare:
        hourly_cb = city_callback('hourly_cmp_', city_name)
        rain_cb = city_callback('rain_cmp_', city_name)
        week_cb = city_callback('week_forecast_cmp_', city_name)
        extra_cb = city_callback('extra_cmp_', city_name)
        refresh_cb = city_callback('refresh_weather_cmp_', city_name)
    else:
        hourly_cb = city_callback('hourly_', city_name)
        rain_cb = city_callback('rain_', city_name)
        week_cb = city_callback('week_forecast_', city_name)
        extra_cb = city_callback('extra_', city_name)
        refresh_cb = city_callback('refresh_weather_', city_name)
    keyboard.append([
        InlineKeyboardButton(f"{HOURLY} По часам" if lang == 'rus' else f"{HOURLY} Hourly", callback_data=hourly_cb),
        InlineKeyboardButton(f"{RAIN} Осадки" if lang == 'rus' else f"{RAIN} Precipitation", callback_data=rain_cb)
    ])
    row3 = [InlineKeyboardButton(f"{WEEKLY_FORECAST} Неделя" if lang == 'rus' else f"{WEEKLY_FORECAST} Weekly", callback_data=week_cb)]
    if show_extra_data_btn:
        row3.append(InlineKeyboardButton(f"{EXTRA_DATA} Доп. данные" if lang == 'rus' else f"{EXTRA_DATA} Extra data", callback_data=extra_cb))
    keyboard.append(row3)

    if settings.get('show_refresh_btn', False):
        keyboard.append([InlineKeyboardButton(f'{UPDATES} ' + ('Обновить' if lang == 'rus' else 'Refresh'), callback_data=refresh_cb)])

    # Четвертая строка: навигация назад
    nav_row = []
    if from_favorites and safe_id:
        # ИСПРАВЛЕНИЕ: используем callback "favorites" вместо "weather_fav_{safe_id}"
        nav_row.append(InlineKeyboardButton(
            f"{BACK} Назад" if lang == "rus" else f"{BACK} Back",
            callback_data="favorites"
        ))
    if back_to_compare:
        nav_row.append(InlineKeyboardButton(
            f"{BACK} Назад" if lang == "rus" else f"{BACK} Back",
            callback_data="back_to_compare"
        ))
    if nav_row:
        keyboard.append(nav_row)
    
    return InlineKeyboardMarkup(keyboard)

def create_compare_result_keyboard(city1: str, city2: str, lang: str,
                                   settings: dict=None, saved: bool=False,
                                   favorite_view: bool=False):
    """В избранном сравнение не содержит кнопок городов и нового сравнения."""
    if favorite_view:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(f'{BACK} ' + ('Назад к избранному' if lang == 'rus' else 'Back to favorites'),
                                 callback_data='favorites')
        ]])
    keyboard = [[
        InlineKeyboardButton(f'{WEATHER} {city1}', callback_data=city_callback('view_compare_city_', city1)),
        InlineKeyboardButton(f'{WEATHER} {city2}', callback_data=city_callback('view_compare_city_', city2))
    ]]
    keyboard.append([
        InlineKeyboardButton(f'{COMPARE} ' + ('Начать новое сравнение' if lang == 'rus' else 'New comparison'),
                             callback_data='start_new_compare'),
        InlineKeyboardButton(
            (f'{TRASH} ' + ('Удалить из избранного' if lang == 'rus' else 'Remove from favorites')) if saved else
            (f'{FAVORITES} ' + ('Добавить в избранное' if lang == 'rus' else 'Add to favorites')),
            callback_data='compare_remove_saved' if saved else 'compare_save'
        )
    ])
    if (settings or {}).get('show_refresh_btn', False):
        keyboard.append([
            InlineKeyboardButton(f'{UPDATES} ' + ('Обновить' if lang == 'rus' else 'Refresh'),
                                 callback_data='refresh_compare')
        ])
    return InlineKeyboardMarkup(keyboard)


def create_admin_panel_keyboard(lang: str):
    if lang == "rus":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{BROADCAST} Рассылка всем", callback_data="admin_broadcast")],
            [InlineKeyboardButton(f"{BROADCAST} Рассылка пользователю", callback_data="admin_broadcast_user")],
            [InlineKeyboardButton(f"{USERS_LIST} Все пользователи", callback_data="admin_users_list")],
            [InlineKeyboardButton(f"{UPDATES} Проверить пользователей", callback_data="admin_check_users")]
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{BROADCAST} Broadcast to all", callback_data="admin_broadcast")],
            [InlineKeyboardButton(f"{BROADCAST} Broadcast to user", callback_data="admin_broadcast_user")],
            [InlineKeyboardButton(f"{USERS_LIST} All users", callback_data="admin_users_list")],
            [InlineKeyboardButton(f"{UPDATES} Check users", callback_data="admin_check_users")]
        ])


def create_user_list_keyboard(users: dict, lang: str):
    keyboard = []
    for user_id, user_data in sorted(users.items()):
        username = user_data.get('username', 'N/A')
        first_name = user_data.get('first_name', '')
        display_name = f"@{username}" if username else first_name
        if not display_name or display_name == "@None":
            display_name = f"User {user_id}"
        
        keyboard.append([
            InlineKeyboardButton(
                f"{USER} {display_name} ({user_id})",
                callback_data=f"admin_user_detail_{user_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton(f"{BACK} Назад" if lang == "rus" else f"{BACK} Back", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)


def create_user_detail_keyboard(user_id: int, lang: str):
    if lang == 'rus':
        buttons = [
            [InlineKeyboardButton(f'{BROADCAST} Написать пользователю', callback_data=f'admin_direct_message_{user_id}')],
            [InlineKeyboardButton(f'{ACTIVATION_KEY} Повысить до ADV', callback_data=f'admin_promote_{user_id}')],
            [InlineKeyboardButton(f'{CROSS} Понизить до Basic', callback_data=f'admin_demote_{user_id}')],
            [InlineKeyboardButton(f'{BACK} Назад к списку', callback_data='admin_users_list')],
            [InlineKeyboardButton(f'{BACK} В админку', callback_data='admin_panel')],
        ]
    else:
        buttons = [
            [InlineKeyboardButton(f'{BROADCAST} Message user', callback_data=f'admin_direct_message_{user_id}')],
            [InlineKeyboardButton(f'{ACTIVATION_KEY} Promote to ADV', callback_data=f'admin_promote_{user_id}')],
            [InlineKeyboardButton(f'{CROSS} Demote to Basic', callback_data=f'admin_demote_{user_id}')],
            [InlineKeyboardButton(f'{BACK} Back to list', callback_data='admin_users_list')],
            [InlineKeyboardButton(f'{BACK} To admin', callback_data='admin_panel')],
        ]
    return InlineKeyboardMarkup(buttons)
