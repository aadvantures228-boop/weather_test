from handlers import navigation
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import CallbackContext
from telegram.error import BadRequest
import storage
from config.emojis import *
from config.defaults import DEFAULT_SETTINGS, SETTINGS_NAMES, SETTINGS_VALUES, SETTINGS_VALUES_ENG
from config.texts import ui
import logging
import utils

logger = logging.getLogger(__name__)


def get_setting_display_value(setting_key: str, value: str, lang: str):
    """Получить отображаемое значение настройки"""
    values_dict = SETTINGS_VALUES if lang == "rus" else SETTINGS_VALUES_ENG
    allowed = values_dict.get(setting_key, {})
    
    if not value or value not in allowed:
        value = DEFAULT_SETTINGS.get(setting_key, '')
    
    return allowed.get(value, str(value))


async def show_settings_menu(update: Update, context: CallbackContext):
    query = update.callback_query if hasattr(update, 'callback_query') else None
    user_id = update.effective_user.id if update.message else query.from_user.id
    lang = await storage.get_user_lang(context, user_id)

    if lang == "rus":
        text = ui('settings_main',lang)
        keyboard = [
            [InlineKeyboardButton(f"{PRESSURE} Настройки вывода", callback_data="settings_display")],
            [InlineKeyboardButton(f"{LANGUAGE} Язык", callback_data="settings_language")],
            [InlineKeyboardButton(f"{LOCATION} Мой регион", callback_data="settings_region")],
            [InlineKeyboardButton(f"{QUESTION} Помощь", callback_data="settings_help")]
        ]
    else:
        text = ui('settings_main',lang)
        keyboard = [
            [InlineKeyboardButton(f"{PRESSURE} Display Settings", callback_data="settings_display")],
            [InlineKeyboardButton(f"{LANGUAGE} Language", callback_data="settings_language")],
            [InlineKeyboardButton(f"{LOCATION} My Region", callback_data="settings_region")],
            [InlineKeyboardButton(f"{QUESTION} Help", callback_data="settings_help")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif query:
        try:
            await navigation.edit(query, context, text, reply_markup=reply_markup, parse_mode="HTML")
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                logger.error(f"Error: {e}")


async def show_display_settings(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)
    settings = await storage.get_user_settings(context, user_id)

    temp_value = get_setting_display_value('temperature', settings.get('temperature'), lang)
    pressure_value = get_setting_display_value('pressure', settings.get('pressure'), lang)
    time_value = get_setting_display_value('time_format', settings.get('time_format'), lang)
    wind_value = get_setting_display_value('wind_speed', settings.get('wind_speed'), lang)

    if lang == "rus":
        text = ui('settings_display',lang)
        keyboard = [
            [InlineKeyboardButton(f"{THERMOMETER} Температура: {temp_value}", callback_data="settings_temp")],
            [InlineKeyboardButton(f"{PRESSURE} Давление: {pressure_value}", callback_data="settings_pressure")],
            [InlineKeyboardButton(f"{HOURLY} Время: {time_value}", callback_data="settings_time")],
            [InlineKeyboardButton(f"{WIND} Ветер: {wind_value}", callback_data="settings_wind")],
            [InlineKeyboardButton(f"{EXTRA_DATA} Дополнительные данные", callback_data="settings_extra_data")],
            [InlineKeyboardButton(f"{LOCATION} Дополнительные кнопки", callback_data="settings_extra_buttons")],
            [InlineKeyboardButton(f"{BACK} Назад", callback_data="settings_menu")]
        ]
    else:
        text = ui('settings_display',lang)
        keyboard = [
            [InlineKeyboardButton(f"{THERMOMETER} Temperature: {temp_value}", callback_data="settings_temp")],
            [InlineKeyboardButton(f"{PRESSURE} Pressure: {pressure_value}", callback_data="settings_pressure")],
            [InlineKeyboardButton(f"{HOURLY} Time: {time_value}", callback_data="settings_time")],
            [InlineKeyboardButton(f"{WIND} Wind: {wind_value}", callback_data="settings_wind")],
            [InlineKeyboardButton(f"{EXTRA_DATA} Extra Data", callback_data="settings_extra_data")],
            [InlineKeyboardButton(f"{LOCATION} Extra Buttons", callback_data="settings_extra_buttons")],
            [InlineKeyboardButton(f"{BACK} Back", callback_data="settings_menu")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await navigation.edit(query, context, text, reply_markup=reply_markup, parse_mode="HTML")
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.error(f"Error: {e}")


async def show_setting_choice(update: Update, context: CallbackContext, setting_key: str, remember=True):
    query = update.callback_query
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)
    settings = await storage.get_user_settings(context, user_id)

    current_value = settings.get(setting_key)
    if not current_value:
        current_value = DEFAULT_SETTINGS.get(setting_key, '')
    
    current_display = get_setting_display_value(setting_key, current_value, lang)
    
    names_dict = SETTINGS_NAMES.get(lang, {})
    name = names_dict.get(setting_key, setting_key)

    values_dict = SETTINGS_VALUES if lang == "rus" else SETTINGS_VALUES_ENG
    values = values_dict.get(setting_key, {})

    text = f"{SETTINGS} <b>{name}</b>\n\nТекущее значение: {current_display}\n\nВыберите:" if lang == "rus" else f"{SETTINGS} <b>{name}</b>\n\nCurrent value: {current_display}\n\nChoose:"

    keyboard = []
    for key, display in values.items():
        prefix = f"{CHECK} " if key == current_value else ""
        callback = f"settings_set_{setting_key}_{key}"
        keyboard.append([InlineKeyboardButton(f"{prefix}{display}", callback_data=callback)])

    keyboard.append([InlineKeyboardButton(f"{BACK} Назад" if lang == "rus" else f"{BACK} Back", callback_data="settings_display")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await navigation.edit(query, context, text, reply_markup=reply_markup, parse_mode="HTML", remember=remember)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.error(f"Error: {e}")


async def set_setting_value(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    parts = data.split("_")
    if len(parts) >= 4:
        setting_value = parts[-1]
        setting_key = "_".join(parts[2:-1])

        await storage.set_user_setting(context, user_id, setting_key, setting_value)
        
        lang = await storage.get_user_lang(context, user_id)

        if setting_key == 'language':
            current_region = await storage.get_user_region(context, user_id)
            if current_region:
                translated_region = storage.translate_city(current_region, lang)
                await storage.set_user_region(context, user_id, translated_region)
            
            await show_language_settings(update, context)
            
            if lang == "rus":
                keyboard = [
                    [f"{SETTINGS} Настройки", f"{FAVORITES} Избранное"],
                    [f"{SUNRISE} Погода в моем регионе", f"{UPDATES} Обновления"],
                    [f"{COMPARE} Сравнить"]
                ]
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"{CHECK} Язык изменен на Русский. Все кнопки обновлены.",
                    reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                )
            else:
                keyboard = [
                    [f"{SETTINGS} Settings", f"{FAVORITES} Favorites"],
                    [f"{SUNRISE} Weather in my region", f"{UPDATES} Updates"],
                    [f"{COMPARE} Compare"]
                ]
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"{CHECK} Language changed to English. All buttons updated.",
                    reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                )
            return

        await show_setting_choice(update, context, setting_key, remember=False)


async def show_extra_data_settings(update: Update, context: CallbackContext, remember=True):
    query = update.callback_query
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)
    settings = await storage.get_user_settings(context, user_id)

    extra_items = ['show_clouds', 'show_wind_direction', 'show_sunrise_sunset', 'show_wind_gust',
                   'show_dew_point', 'show_visibility', 'show_pressure_sea']
    text = ui('settings_extra',lang)

    keyboard = []
    for item in extra_items:
        names_dict = SETTINGS_NAMES.get(lang, {})
        name = names_dict.get(item, item)
        is_enabled = settings.get(item, DEFAULT_SETTINGS.get(item, True))
        status = CHECK if is_enabled else CROSS
        callback = f"settings_toggle_extra_{item}"
        keyboard.append([InlineKeyboardButton(f"{name}: {status}", callback_data=callback)])

    keyboard.append([InlineKeyboardButton(f"{BACK} Назад" if lang == "rus" else f"{BACK} Back", callback_data="settings_display")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await navigation.edit(query, context, text, reply_markup=reply_markup, parse_mode="HTML", remember=remember)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.error(f"Error: {e}")


async def toggle_extra_setting(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)

    parts = data.split("_")
    if len(parts) >= 4:
        setting_key = "_".join(parts[3:])
        
        settings = await storage.get_user_settings(context, user_id)
        current_value = settings.get(setting_key, DEFAULT_SETTINGS.get(setting_key, True))
        new_value = not current_value
        
        await storage.set_user_setting(context, user_id, setting_key, new_value)
        
        msg = "Включено" if new_value else "Выключено"
        # Callback уже подтверждён диспетчером; повторный answer может вызвать ошибку.
        
        await show_extra_data_settings(update, context, remember=False)


async def show_extra_buttons_settings(update: Update, context: CallbackContext, remember=True):
    query = update.callback_query
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)
    settings = await storage.get_user_settings(context, user_id)

    button_items = ['show_extra_data_btn', 'show_set_region_btn', 'show_refresh_btn']
    text = ui('settings_buttons',lang)

    keyboard = []
    for item in button_items:
        names_dict = SETTINGS_NAMES.get(lang, {})
        name = names_dict.get(item, item)
        is_enabled = settings.get(item, DEFAULT_SETTINGS.get(item, True))
        status = CHECK if is_enabled else CROSS
        callback = f"settings_toggle_button_{item}"
        keyboard.append([InlineKeyboardButton(f"{name}: {status}", callback_data=callback)])

    keyboard.append([InlineKeyboardButton(f"{BACK} Назад" if lang == "rus" else f"{BACK} Back", callback_data="settings_display")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await navigation.edit(query, context, text, reply_markup=reply_markup, parse_mode="HTML", remember=remember)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.error(f"Error: {e}")


async def toggle_button_setting(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)

    parts = data.split("_")
    if len(parts) >= 4:
        setting_key = "_".join(parts[3:])
        
        settings = await storage.get_user_settings(context, user_id)
        current_value = settings.get(setting_key, DEFAULT_SETTINGS.get(setting_key, True))
        new_value = not current_value
        
        await storage.set_user_setting(context, user_id, setting_key, new_value)
        
        msg = "Включено" if new_value else "Выключено"
        # Callback уже подтверждён диспетчером; повторный answer может вызвать ошибку.
        
        await show_extra_buttons_settings(update, context, remember=False)


async def show_language_settings(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)
    settings = await storage.get_user_settings(context, user_id)
    current_lang = settings.get('language', 'rus')

    text = f"{LANGUAGE} <b>Язык</b>\n\nТекущий язык: {'Русский' if current_lang == 'rus' else 'English'}\n\nВыберите:" if lang == "rus" else f"{LANGUAGE} <b>Language</b>\n\nCurrent language: {'Russian' if current_lang == 'rus' else 'English'}\n\nChoose:"

    keyboard = [
        [InlineKeyboardButton(f"{CHECK if current_lang == 'rus' else ''}{FLAG_RU} Русский", callback_data="settings_set_language_rus")],
        [InlineKeyboardButton(f"{CHECK if current_lang == 'eng' else ''}{FLAG_US} English", callback_data="settings_set_language_eng")],
        [InlineKeyboardButton(f"{BACK} Назад" if lang == "rus" else f"{BACK} Back", callback_data="settings_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await navigation.edit(query, context, text, reply_markup=reply_markup, parse_mode="HTML")
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.error(f"Error: {e}")


async def show_region_settings(update: Update, context: CallbackContext):
    context.user_data['awaiting_region_from_settings'] = False
    
    query = update.callback_query
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)

    region = await storage.get_user_region(context, user_id)
    region_display = region if region else ("не выбран" if lang == "rus" else "not selected")

    if region:
        change_btn_text = f"{LOCATION} Сменить регион" if lang == "rus" else f"{LOCATION} Change region"
    else:
        change_btn_text = f"{LOCATION} Выбрать регион" if lang == "rus" else f"{LOCATION} Select region"

    if lang == "rus":
        text = f"{LOCATION} <b>Мой регион</b>\n\nТекущий регион: {region_display}\n\n"
        keyboard = [
            [InlineKeyboardButton(change_btn_text, callback_data="settings_change_region")],
            [InlineKeyboardButton(f"{BACK} Назад", callback_data="settings_menu")]
        ]
    else:
        text = f"{LOCATION} <b>My Region</b>\n\nCurrent region: {region_display}\n\n"
        keyboard = [
            [InlineKeyboardButton(change_btn_text, callback_data="settings_change_region")],
            [InlineKeyboardButton(f"{BACK} Back", callback_data="settings_menu")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await navigation.edit(query, context, text, reply_markup=reply_markup, parse_mode="HTML")
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.error(f"Error: {e}")


async def start_region_change(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)

    if lang == "rus":
        text = (f"{LOCATION} <b>Смена региона</b>\n\n"
                f"Введите название нового региона прямо в чат,\n"
                f"и он автоматически станет вашим регионом.\n\n"
                f"Для отмены нажмите кнопку ниже.")
        keyboard = [[InlineKeyboardButton(f"{CROSS} Отмена", callback_data="nav_back")]]
    else:
        text = (f"{LOCATION} <b>Change Region</b>\n\n"
                f"Enter the new region name directly in the chat,\n"
                f"and it will automatically become your region.\n\n"
                f"To cancel, press the button below.")
        keyboard = [[InlineKeyboardButton(f"{CROSS} Cancel", callback_data="nav_back")]]

    context.user_data['awaiting_region_from_settings'] = True
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await navigation.edit(query, context, text, reply_markup=reply_markup, parse_mode="HTML")
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.error(f"Error: {e}")


async def show_help(update: Update, context: CallbackContext):
    """Настройки → Помощь сразу открывает единственный экран новостей."""
    return await show_help_info(update, context)


async def show_help_info(update: Update, context: CallbackContext):
    """Старый callback оставлен ради уже отправленных сообщений Beta 1.1."""
    query = update.callback_query
    lang = await storage.get_user_lang(context, query.from_user.id)
    text = ui('settings_help', lang)
    keyboard = [[InlineKeyboardButton(f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back'), callback_data='settings_menu')]]
    await navigation.edit(query, context, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def change_language(update: Update, context: CallbackContext, lang: str):
    """Смена языка через callback"""
    query = update.callback_query
    user_id = query.from_user.id
    
    await storage.set_user_setting(context, user_id, 'language', lang)
    
    current_region = await storage.get_user_region(context, user_id)
    if current_region:
        translated_region = storage.translate_city(current_region, lang)
        await storage.set_user_region(context, user_id, translated_region)
    
    if lang == "rus":
        keyboard = [
            [f"{SETTINGS} Настройки", f"{FAVORITES} Избранное"],
            [f"{SUNRISE} Погода в моем регионе", f"{UPDATES} Обновления"],
            [f"{COMPARE} Сравнить"]
        ]
        text = f"{CHECK} Язык изменен на Русский. Все кнопки обновлены."
    else:
        keyboard = [
            [f"{SETTINGS} Settings", f"{FAVORITES} Favorites"],
            [f"{SUNRISE} Weather in my region", f"{UPDATES} Updates"],
            [f"{COMPARE} Compare"]
        ]
        text = f"{CHECK} Language changed to English. All buttons updated."
    
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    await show_language_settings(update, context)