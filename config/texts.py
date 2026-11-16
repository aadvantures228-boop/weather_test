"""Локализованные пользовательские тексты и история версий. Логика здесь отсутствует."""
from config.emojis import *

VERSION = 'Release 1.1'
NEWS_URL = 'https://t.me/weather_worldmap'

UI = {
    'rus': {
        'start': f'{WEATHER} Добро пожаловать в погодный бот!\n{INFO} Текущая версия: {VERSION}\n\nПокажу погоду в любом городе мира.\n{CITY} Напишите название города или используйте кнопки ниже.',
        'settings_main': f'{SETTINGS} <b>Главное меню настроек</b>\n\nВыберите категорию:',
        'settings_display': f'{PRESSURE} <b>Настройки вывода</b>\n\nОсновные единицы:',
        'settings_extra': f'{EXTRA_DATA} <b>Дополнительные данные</b>\n\nПоказывать:',
        'settings_buttons': f'{LOCATION} <b>Дополнительные кнопки</b>\n\nПоказывать:',
        'activation_prompt': f'{ACTIVATION_KEY} <b>Активация</b>\n\nВведите ключ активации. Для отмены: /cancel',
        'region_missing': f'{LOCATION} Вы ещё не выбрали свой регион!\n\nВведите название города прямо в чат, и он автоматически станет вашим регионом.',
        'admin_broadcast_prompt': f'{BROADCAST} <b>Рассылка всем пользователям</b>\n\nВведите сообщение, которое получат пользователи бота.\n\nДля отмены: /cancel',
        'admin_legacy_message_prompt': f'{BROADCAST} <b>Рассылка пользователю</b>\n\nВведите числовой ID пользователя.\n\nДля отмены: /cancel',
        'settings_help': f'{INFO} <b>Новости</b>\n\nОбновления бота: <a href="{NEWS_URL}">{NEWS_URL}</a>',
        'settings_updates': f'{UPDATES} <b>История обновлений</b>\nВыберите версию:',
        'admin_menu': f'{ADMIN} <b>Админ-панель</b>\n\nВыберите действие:',
        'admin_users': f'{USERS_LIST} <b>Все пользователи ({{count}})</b>:',
        'admin_message_prompt': f'{BROADCAST} <b>Сообщение пользователю {{user_id}}</b>\n\nВведите текст сообщения. Для отмены используйте кнопку «Назад» или /cancel.',
        'admin_promote_prompt': f'{ACTIVATION_KEY} <b>Повышение пользователя {{user_id}}</b>\n\nВведите один из действующих ADV-ключей. Для отмены — «Назад» или /cancel.',
        'admin_sent': f'{CHECK} Сообщение отправлено пользователю {{user_id}}.',
        'admin_promoted': f'{CHECK} Уровень пользователя {{user_id}} повышен до ADV.',
        'admin_demoted': f'{CHECK} Пользователь {{user_id}} переведён на Basic.',
        'admin_invalid_key': f'{CROSS} Ключ недействителен. Введите действующий ADV-ключ или нажмите «Назад».',
        'admin_recipient_promoted': f'{CHECK} Ваш уровень доступа изменён на ADV.',
        'admin_recipient_demoted': f'{INFO} Ваш уровень доступа изменён на Basic.',
        'admin_recipient_message': f'{BROADCAST} <b>Сообщение от администратора:</b>\n\n{{message}}',
        'compare_first': f'{COMPARE} <b>Сравнение городов</b>\n\nВведите название первого города:',
        'compare_second': f'{CHECK} Отлично! Теперь введите второй город:',
        'compare_same': f'{WARNING} Для сравнения нужны разные города. Введите другой город:',
        'compare_invalid': f'{CROSS} Город «{{city}}» не найден. Попробуйте ещё раз или /cancel.',
        'processing': f'{HOURGLASS} Запрос обрабатывается…',
        'already_processing': f'{HOURGLASS} Запрос уже обрабатывается. / Request in progress.',
        'invalid_city': f'{CROSS} Не удалось определить населённый пункт. Проверьте название города.',
        'extra_location': f'{EXTRA_DATA} Дополнительные данные для {{city}}:\n\n{GLOBE} Страна: {{country}}{{region}}\n{LOCATION} Координаты: <code>{{coordinates}}</code>\n{HOURLY} {{timezone}}',
    },
    'eng': {
        'start': f'{WEATHER} Welcome to the weather bot!\n{INFO} Current version: {VERSION}\n\nGet weather for cities around the world.\n{CITY} Type a city name or use the buttons below.',
        'settings_main': f'{SETTINGS} <b>Main Settings Menu</b>\n\nChoose category:',
        'settings_display': f'{PRESSURE} <b>Display Settings</b>\n\nMain units:',
        'settings_extra': f'{EXTRA_DATA} <b>Extra Data</b>\n\nShow:',
        'settings_buttons': f'{LOCATION} <b>Extra Buttons</b>\n\nShow:',
        'activation_prompt': f'{ACTIVATION_KEY} <b>Activation</b>\n\nEnter your activation key. To cancel: /cancel',
        'region_missing': f'{LOCATION} You have not selected your region!\n\nType a city name in chat, and it will become your region.',
        'admin_broadcast_prompt': f'{BROADCAST} <b>Broadcast to all users</b>\n\nEnter the message to send to bot users.\n\nTo cancel: /cancel',
        'admin_legacy_message_prompt': f'{BROADCAST} <b>Message a user</b>\n\nEnter the numeric user ID.\n\nTo cancel: /cancel',
        'settings_help': f'{INFO} <b>News</b>\n\nBot updates: <a href="{NEWS_URL}">{NEWS_URL}</a>',
        'settings_updates': f'{UPDATES} <b>Update History</b>\nChoose version:',
        'admin_menu': f'{ADMIN} <b>Admin Panel</b>\n\nChoose action:',
        'admin_users': f'{USERS_LIST} <b>All users ({{count}})</b>:',
        'admin_message_prompt': f'{BROADCAST} <b>Message user {{user_id}}</b>\n\nEnter your message. Use Back or /cancel to cancel.',
        'admin_promote_prompt': f'{ACTIVATION_KEY} <b>Promote user {{user_id}}</b>\n\nEnter a valid ADV activation key. Use Back or /cancel to cancel.',
        'admin_sent': f'{CHECK} Message sent to user {{user_id}}.',
        'admin_promoted': f'{CHECK} User {{user_id}} promoted to ADV.',
        'admin_demoted': f'{CHECK} User {{user_id}} moved to Basic.',
        'admin_invalid_key': f'{CROSS} Invalid key. Enter a valid ADV key or press Back.',
        'admin_recipient_promoted': f'{CHECK} Your access level is now ADV.',
        'admin_recipient_demoted': f'{INFO} Your access level is now Basic.',
        'admin_recipient_message': f'{BROADCAST} <b>Message from an administrator:</b>\n\n{{message}}',
        'compare_first': f'{COMPARE} <b>City comparison</b>\n\nEnter the first city:',
        'compare_second': f'{CHECK} Great! Enter the second city:',
        'compare_same': f'{WARNING} Please select two different cities:',
        'compare_invalid': f'{CROSS} City «{{city}}» not found. Try again or /cancel.',
        'processing': f'{HOURGLASS} Processing request…',
        'already_processing': f'{HOURGLASS} Request in progress. / Запрос уже обрабатывается.',
        'invalid_city': f'{CROSS} City not found. Check the spelling and try again.',
        'extra_location': f'{EXTRA_DATA} Extra data for {{city}}:\n\n{GLOBE} Country: {{country}}{{region}}\n{LOCATION} Coordinates: <code>{{coordinates}}</code>\n{HOURLY} {{timezone}}',
    },
}

def ui(key, lang='rus', **values):
    template = UI['eng' if lang == 'eng' else 'rus'][key]
    return template.format(**values) if values else template


def changelog(version, lang='rus'):
    texts_rus = {
        "release_1_1": (
            f"{RELEASE} <b>Release 1.1</b>\n\n"
            "• Избранные сравнения: сохраняйте пары городов и открывайте их одним нажатием.\n"
            "• Необязательная кнопка «Обновить» для погоды и сравнения.\n"
            "• Расширенный прогноз: 20 часов подробно, затем до 5 дней с шагом 3 часа.\n"
            "• Осадки по отдельным интервалам: дождь, снег и грозы, даже когда они идут одновременно.\n"
            "• Штормовые предупреждения теперь доступны всем пользователям.\n"
            "• Исправлены ошибки региона, избранного и отображения погоды."
        ),

        "pre_1_1_2": f"{PATCH} <b>Pre-release 1.1-2</b>\n\n• Исправлен поиск городов и защита от ошибочного ввода.\n• Избранное распознаёт один город на разных языках.\n• Новые необязательные показатели: точка росы, видимость, давление на уровне моря и поверхности.\n• Координаты стало удобнее копировать.\n• Удобнее управление погодными показателями.",
        "1_0": f"{RELEASE} <b>Release 1.0</b>\n\n• Кнопка «Сделать моим регионом» скрыта, если город уже является регионом.\n• При добавлении/удалении из избранного кнопка меняется мгновенно.\n• Список избранного обновляется автоматически.\n• Удобное меню истории обновлений.",
        "1_0_1": f"{PATCH} <b>1.0.1</b>\n\n• Убрано сообщение «Загружаю прогноз» при повторном открытии.\n• Детальный прогноз дня открывается вместо меню дней.\n• Добавлена кнопка «Сводка».\n• Почасовой прогноз на сегодня.\n• Восход и закат по местному времени.",
        "1_0_2": f"{PATCH} <b>1.0.2</b>\n\n• Доп. данные: страна, область, часовой пояс, координаты.\n• Сравнение погоды двух городов (через главное меню).\n• Добавлена кнопка «Доп. данные» в меню погоды.\n• Добавлена команда /cancel для отмены любых процессов.",
        "1_0_3": f"{PATCH} <b>1.0.3</b>\n\n• Настройки единиц измерения: температура (°C/°F), давление, ветер, время.\n• Управление отображением кнопок и доп. данных в настройках.\n• Смена региона через меню настроек.\n• Сводка на завтра в почасовом прогнозе.\n• Прогноз осадков (дождь/снег) на сегодня и завтра.",
        "pre_1_1_1": (f"{PATCH} <b>Pre-release 1.1-1</b>\n\n"
                       "• Текущая погода стала загружаться быстрее.\n"
                       "• Прогнозы по часам, дням и осадкам работают стабильнее.\n"
                       "• Исправлены настройки погоды, часовые пояса и переходы между меню.\n"
                       "• При долгой загрузке появляется сообщение ожидания.\n"
                       "• Убран поминутный прогноз, обновлена помощь.\n"
                       "• Улучшены переводы погодных условий."),
        "1_1": (
            f"{BETA} <b>Beta 1.1</b>\n\n"
            f"• Интеграция One Call API 4.0 с автоматическим fallback на старый API\n"
            f"• Прогноз на 8 дней вперед с детальными данными\n"
            f"• Почасовой прогноз с пагинацией (по 12 часов на страницу)\n"
            f"• Осадки группируются по диапазонам времени\n"
            f"• Добавлена база данных для хранения пользователей\n"
            f"• Исправлен баг с дубликатами городов в избранном"
        ),
        "beta": f"{BETA} <b>Beta 1.0</b>\n\n• Базовый просмотр погоды.\n• Прогноз на неделю.\n• Избранное.\n• Смена языка."
    }

    texts_eng = {
        "release_1_1": (
            f"{RELEASE} <b>Release 1.1</b>\n\n"
            "• Save city comparisons to favorites and open them with one tap.\n"
            "• Optional Refresh button for weather and comparisons.\n"
            "• Longer forecast: 20 detailed hours, then 3-hour steps up to 5 days.\n"
            "• Independent rain, snow and thunderstorm time ranges, including overlaps.\n"
            "• Weather alerts are now available to everyone.\n"
            "• Fixed region, favorites and weather display issues."
        ),

        "pre_1_1_2": f"{PATCH} <b>Pre-release 1.1-2</b>\n\n• Improved city search and invalid input handling.\n• Favorites recognize the same city across languages.\n• Optional dew point, visibility and sea/ground pressure.\n• Easier copying of coordinates.\n• Easier weather display settings.",
        "1_0": f"{RELEASE} <b>Release 1.0</b>\n\n• 'Set as my region' hidden if already region.\n• Favorites button toggles instantly.\n• Favorites list auto-refreshes.\n• Convenient update history menu.",
        "1_0_1": f"{PATCH} <b>1.0.1</b>\n\n• Removed 'Loading forecast' message.\n• Daily forecast opens instead of day menu.\n• Added 'Summary' button.\n• Hourly forecast for today.\n• Sunrise/sunset in local time.",
        "1_0_2": f"{PATCH} <b>1.0.2</b>\n\n• Extra data: country, region, timezone, coordinates.\n• Compare weather (via main menu).\n• Added 'More info' button to weather menu.\n• Added /cancel command to abort any processes.",
        "1_0_3": f"{PATCH} <b>1.0.3</b>\n\n• Unit settings: temperature (°C/°F), pressure, wind, time format.\n• Control display of buttons and extra data in settings.\n• Change region via settings menu.\n• Tomorrow's summary in hourly forecast.\n• Precipitation forecast (rain/snow) for today and tomorrow.",
        "pre_1_1_1": (f"{PATCH} <b>Pre-release 1.1-1</b>\n\n"
                       "• Current weather loads faster.\n"
                       "• More reliable hourly, daily and precipitation forecasts.\n"
                       "• Fixed weather settings, time zones and menu navigation.\n"
                       "• Progress messages appear for longer requests.\n"
                       "• Removed minutely forecast and simplified help.\n"
                       "• Improved weather translations."),
        "1_1": (
            f"{BETA} <b>Beta 1.1</b>\n\n"
            f"• One Call API 4.0 integration with automatic fallback to old API\n"
            f"• 8-day forecast with detailed data\n"
            f"• Hourly forecast with pagination (12 hours per page)\n"
            f"• Precipitation grouped by time ranges\n"
            f"• Added database for user storage\n"
            f"• Fixed duplicate cities bug in favorites"
        ),
        "beta": f"{BETA} <b>Beta 1.0</b>\n\n• Basic weather viewing.\n• Weekly forecast.\n• Favorites.\n• Language change."
    }

    texts = texts_rus if lang == 'rus' else texts_eng
    return texts.get(version, f'{WARNING} ' + ('Нет данных' if lang == 'rus' else 'No details'))
