"""Форматирование метеоданных без дополнительных запросов к API."""
from datetime import datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config.defaults import DEFAULT_SETTINGS
from config.emojis import (
    WEATHER, THERMOMETER, DESCRIPTION, HUMIDITY, PRESSURE, WIND,
    CLOUDS, SUNRISE, SUNSET, VISIBILITY
)


def effective_settings(settings=None, api_units='metric'):
    values = DEFAULT_SETTINGS.copy()
    if settings:
        values.update(settings)
    elif api_units == 'imperial':
        values['temperature'] = 'fahrenheit'
    return values


def local_timezone(offset=0, tz_name=None):
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    try:
        return timezone(timedelta(seconds=int(offset or 0)))
    except (ValueError, OverflowError, TypeError):
        return timezone.utc


def local_datetime(timestamp, offset=0, tz_name=None):
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).astimezone(local_timezone(offset, tz_name))


def format_time(timestamp, settings=None, offset=0, tz_name=None):
    if timestamp is None:
        return '—'
    fmt = '%I:%M %p' if (settings or {}).get('time_format') == '12h' else '%H:%M'
    result = local_datetime(timestamp, offset, tz_name).strftime(fmt)
    return result.lstrip('0') if fmt.startswith('%I') else result


def temperature(value, settings=None, digits=0):
    if value is None:
        return '—'
    if (settings or {}).get('temperature') == 'fahrenheit':
        return f"{float(value)*9/5+32:.{digits}f}°F"
    return f"{float(value):.{digits}f}°C"


def pressure(value, settings=None, lang='rus'):
    if value is None:
        return '—'
    if (settings or {}).get('pressure', 'mmhg') == 'hpa':
        return f'{round(float(value))} hPa'
    return f'{round(float(value)*0.750062)} ' + ('мм рт. ст.' if lang == 'rus' else 'mmHg')


def wind(value, settings=None, lang='rus'):
    if value is None:
        return '—'
    unit = (settings or {}).get('wind_speed', 'ms')
    number = float(value)
    if unit == 'kmh':
        number *= 3.6
        suffix = 'км/ч' if lang == 'rus' else 'km/h'
    elif unit == 'mph':
        number *= 2.236936
        suffix = 'mph'
    else:
        suffix = 'м/с' if lang == 'rus' else 'm/s'
    return f'{number:.1f} {suffix}'


def wind_direction(degrees, lang='rus'):
    if degrees is None:
        return '—'
    choices_ru = ['северный', 'северо-восточный', 'восточный', 'юго-восточный', 'южный', 'юго-западный', 'западный', 'северо-западный']
    choices_en = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west']
    return (choices_ru if lang == 'rus' else choices_en)[int((float(degrees) + 22.5) // 45) % 8]


def dew_point_celsius(temp_c, humidity):
    """Формула Магнуса, результат в °C. Никакого обращения к API."""
    try:
        t, rh = float(temp_c), float(humidity)
        if not math.isfinite(t) or not math.isfinite(rh) or not (0 < rh <= 100):
            return None
        gamma = math.log(rh / 100.0) + 17.62 * t / (243.12 + t)
        return 243.12 * gamma / (17.62 - gamma)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def visibility_text(meters, lang='rus'):
    try:
        meters = max(0, float(meters))
        return (f'{meters / 1000:.1f} км' if lang == 'rus' else f'{meters / 1000:.1f} km') if meters >= 1000 else (f'{meters:.0f} м' if lang == 'rus' else f'{meters:.0f} m')
    except (ValueError, TypeError):
        return '—'


def current_text(city, data, lang='rus', settings=None):
    s = effective_settings(settings)
    main = data.get('main') or {}
    wd = data.get('wind') or {}
    weather = data.get('weather') or [{}]
    desc = weather_description(weather[0], lang)
    temp = temperature(main.get('temp'), s)
    feels = temperature(main.get('feels_like'), s)
    humidity = main.get('humidity', '—')
    display_pressure = pressure(main.get('pressure'), s, lang)
    display_wind = wind(wd.get('speed'), s, lang)
    if lang == 'rus':
        result = [f'{WEATHER} Погода в {city}:',
                  f'{THERMOMETER} Температура: {temp} (ощущается как {feels})',
                  f'{DESCRIPTION} Описание: {desc}',
                  f'{HUMIDITY} Влажность: {humidity}%',
                  f'{PRESSURE} Давление: {display_pressure}',
                  f'{WIND} Ветер: {display_wind}']
    else:
        result = [f'{WEATHER} Weather in {city}:',
                  f'{THERMOMETER} Temperature: {temp} (feels like {feels})',
                  f'{DESCRIPTION} Description: {desc}',
                  f'{HUMIDITY} Humidity: {humidity}%',
                  f'{PRESSURE} Pressure: {display_pressure}',
                  f'{WIND} Wind: {display_wind}']
    extra = []
    if s['show_clouds'] and data.get('clouds', {}).get('all') is not None:
        extra.append(f"{CLOUDS} {'Облачность' if lang == 'rus' else 'Cloudiness'}: {data['clouds']['all']}%")
    if s['show_wind_direction'] and wd.get('deg') is not None:
        extra.append(f"{WIND} {'Направление' if lang == 'rus' else 'Direction'}: {wind_direction(wd['deg'],lang)}")
    if s['show_wind_gust'] and wd.get('gust') is not None:
        extra.append(f"{WIND} {'Порывы' if lang == 'rus' else 'Gusts'}: {wind(wd['gust'],s,lang)}")
    sun = data.get('sys') or {}
    if s['show_sunrise_sunset']:
        if sun.get('sunrise') is not None:
            extra.append(f"{SUNRISE} {'Восход' if lang == 'rus' else 'Sunrise'}: {format_time(sun['sunrise'],s,data.get('timezone',0))}")
        if sun.get('sunset') is not None:
            extra.append(f"{SUNSET} {'Закат' if lang == 'rus' else 'Sunset'}: {format_time(sun['sunset'],s,data.get('timezone',0))}")
    if s.get('show_dew_point', False):
        dp = dew_point_celsius(main.get('temp'), main.get('humidity'))
        if dp is not None:
            extra.append(f"{HUMIDITY} {'Точка росы (расчётная)' if lang == 'rus' else 'Dew point (estimated)'}: {temperature(dp,s,1)}")
    if s.get('show_visibility', False) and data.get('visibility') is not None:
        extra.append(f"{VISIBILITY} {'Дальность видимости' if lang == 'rus' else 'Visibility'}: {visibility_text(data['visibility'],lang)}")
    if (s.get('show_pressure_sea', False) and main.get('sea_level') is not None
            and main.get('pressure') is not None
            and round(float(main['sea_level'])) != round(float(main['pressure']))):
        extra.append(f"{PRESSURE} {'Давление на уровне моря' if lang == 'rus' else 'Sea-level pressure'}: {pressure(main['sea_level'],s,lang)}")
    if extra:
        result.extend(['', f"{PRESSURE} {'ДОПОЛНИТЕЛЬНЫЕ ДАННЫЕ' if lang == 'rus' else 'EXTENDED DATA'}:", *extra])
    return '\n'.join(result)


# === Переводы погодных состояний OpenWeather ===
"""Справочник локализации погодных состояний по кодам OpenWeather."""

RU_BY_ID = {
    200: 'гроза с небольшим дождём', 201: 'гроза с дождём',
    202: 'гроза с сильным дождём', 210: 'слабая гроза', 211: 'гроза',
    212: 'сильная гроза', 221: 'местами гроза',
    230: 'гроза с небольшой моросью', 231: 'гроза с моросью',
    232: 'гроза с сильной моросью',
    300: 'слабая морось', 301: 'морось', 302: 'сильная морось',
    310: 'небольшая морось с дождём', 311: 'морось с дождём',
    312: 'сильная морось с дождём', 313: 'ливень с моросью',
    314: 'сильный ливень с моросью', 321: 'ливневая морось',
    500: 'небольшой дождь', 501: 'умеренный дождь', 502: 'сильный дождь',
    503: 'очень сильный дождь', 504: 'ливневый дождь',
    511: 'ледяной дождь', 520: 'небольшой ливень', 521: 'ливень',
    522: 'сильный ливень', 531: 'местами ливень',
    600: 'небольшой снег', 601: 'снег', 602: 'сильный снег',
    611: 'мокрый снег', 612: 'слабый ливневый мокрый снег',
    613: 'ливневый мокрый снег', 615: 'небольшой дождь со снегом',
    616: 'дождь со снегом', 620: 'небольшой снегопад',
    621: 'снегопад', 622: 'сильный снегопад',
    701: 'дымка', 711: 'дым', 721: 'мгла', 731: 'пыльные вихри',
    741: 'туман', 751: 'песок', 761: 'пыль',
    762: 'вулканический пепел', 771: 'шквал', 781: 'торнадо',
    800: 'ясно', 801: 'малооблачно', 802: 'переменная облачность',
    803: 'облачно с прояснениями', 804: 'пасмурно',
}

RU_BY_DESCRIPTION = {
    'clear sky': 'ясно', 'sky is clear': 'ясно',
    'few clouds': 'малооблачно', 'scattered clouds': 'переменная облачность',
    'broken clouds': 'облачно с прояснениями', 'overcast clouds': 'пасмурно',
    'thunderstorm with light rain': 'гроза с небольшим дождём',
    'thunderstorm with rain': 'гроза с дождём',
    'thunderstorm with heavy rain': 'гроза с сильным дождём',
    'light thunderstorm': 'слабая гроза', 'thunderstorm': 'гроза',
    'heavy thunderstorm': 'сильная гроза', 'ragged thunderstorm': 'местами гроза',
    'thunderstorm with light drizzle': 'гроза с небольшой моросью',
    'thunderstorm with drizzle': 'гроза с моросью',
    'thunderstorm with heavy drizzle': 'гроза с сильной моросью',
    'light intensity drizzle': 'слабая морось', 'drizzle': 'морось',
    'heavy intensity drizzle': 'сильная морось',
    'light intensity drizzle rain': 'небольшая морось с дождём',
    'drizzle rain': 'морось с дождём',
    'heavy intensity drizzle rain': 'сильная морось с дождём',
    'shower rain and drizzle': 'ливень с моросью',
    'heavy shower rain and drizzle': 'сильный ливень с моросью',
    'shower drizzle': 'ливневая морось',
    'light rain': 'небольшой дождь', 'moderate rain': 'умеренный дождь',
    'heavy intensity rain': 'сильный дождь',
    'very heavy rain': 'очень сильный дождь', 'extreme rain': 'ливневый дождь',
    'freezing rain': 'ледяной дождь', 'light intensity shower rain': 'небольшой ливень',
    'shower rain': 'ливень', 'heavy intensity shower rain': 'сильный ливень',
    'ragged shower rain': 'местами ливень',
    'light snow': 'небольшой снег', 'snow': 'снег', 'heavy snow': 'сильный снег',
    'sleet': 'мокрый снег', 'light shower sleet': 'слабый ливневый мокрый снег',
    'shower sleet': 'ливневый мокрый снег',
    'light rain and snow': 'небольшой дождь со снегом',
    'rain and snow': 'дождь со снегом',
    'light shower snow': 'небольшой снегопад', 'shower snow': 'снегопад',
    'heavy shower snow': 'сильный снегопад',
    'mist': 'дымка', 'smoke': 'дым', 'haze': 'мгла',
    'sand/dust whirls': 'пыльные вихри', 'fog': 'туман',
    'sand': 'песок', 'dust': 'пыль', 'volcanic ash': 'вулканический пепел',
    'squalls': 'шквал', 'tornado': 'торнадо',
}


def description(weather, lang='rus'):
    """weather — элемент массива weather из API или строка описания."""
    if isinstance(weather, dict):
        code = weather.get('id')
        original = str(weather.get('description') or weather.get('main') or '—')
    else:
        code, original = None, str(weather or '—')
    if lang != 'rus':
        return original
    try:
        if int(code) in RU_BY_ID:
            return RU_BY_ID[int(code)]
    except (TypeError, ValueError):
        pass
    return RU_BY_DESCRIPTION.get(original.strip().casefold(), original)

weather_description = description

# === Интервалы осадков и гроз (hourly / 3-hourly) ===
"""Независимые интервалы дождя, снега и грозы (sweep line / interval scan).

Часовые данные OpenWeather 4.0 описывают час с момента dt.
Бесплатные трёхчасовые данные OpenWeather 2.5 содержат объём за 3 часа,
оканчивающиеся в dt. Временные интервалы считаются непересекающимися.
"""
from datetime import datetime, time, timedelta


def _period(row):
    dt = row['datetime']
    step = max(1, int(row.get('step_hours', 1)))
    if step == 3:
        return row.get('interval_start') or dt - timedelta(hours=3), dt
    return dt, dt + timedelta(hours=1)


def _thunder(row):
    try:
        if 200 <= int(row.get('weather_id') or 0) < 300:
            return True
    except (ValueError, TypeError):
        pass
    return any(word in str(row.get('desc', '')).casefold()
               for word in ('thunder', 'гроза', 'грозы'))


def build_intervals(rows, target_day):
    """Список {'kind','start','end','amount'}; дождь и снег независимы.

    Границы полуночи обрезают интервалы по дате города; объём в
    частично попавшем трёхчасовом отрезке распределяется пропорционально.
    """
    if not rows:
        return []
    zone = rows[0]['datetime'].tzinfo
    beginning = datetime.combine(target_day, time.min, tzinfo=zone)
    end_of_day = beginning + timedelta(days=1)
    pieces = []
    for row in rows:
        start, end = _period(row)
        if end <= beginning or start >= end_of_day:
            continue
        a, b = max(start, beginning), min(end, end_of_day)
        if b <= a:
            continue
        duration = (end - start).total_seconds()
        proportion = (b-a).total_seconds() / duration
        for kind in ('rain', 'snow'):
            amount = max(0.0, float(row.get(kind) or 0)) * proportion
            if amount > 0:
                pieces.append((kind, a, b, amount))
        if _thunder(row):
            pieces.append(('thunder', a, b, 0.0))
    groups = []
    for kind in ('rain', 'snow', 'thunder'):
        series = sorted((x for x in pieces if x[0] == kind), key=lambda x: x[1])
        for _, start, end, amount in series:
            if groups and groups[-1]['kind'] == kind and start <= groups[-1]['end']:
                groups[-1]['end'] = max(groups[-1]['end'], end)
                groups[-1]['amount'] += amount
            else:
                groups.append({'kind': kind, 'start': start, 'end': end, 'amount': amount})
    return sorted(groups, key=lambda g: (g['start'], ('rain','snow','thunder').index(g['kind'])))


def render_intervals(groups, lang='rus', time_format='24h'):
    if not groups:
        return 'Осадков и гроз не ожидается.' if lang == 'rus' else 'No precipitation or thunderstorms expected.'
    names = {'rus': {'rain': '🌧️ Дождь', 'snow': '❄️ Снег', 'thunder': '⛈️ Гроза'},
             'eng': {'rain': '🌧️ Rain', 'snow': '❄️ Snow', 'thunder': '⛈️ Thunderstorm'}}
    fmt = '%I:%M %p' if time_format == '12h' else '%H:%M'
    def show(dt):
        result = dt.strftime(fmt)
        return result.lstrip('0') if time_format == '12h' else result
    lines = []
    for g in groups:
        label = names['eng' if lang == 'eng' else 'rus'][g['kind']]
        count = '' if g['kind'] == 'thunder' else f" — {g['amount']:.1f} " + ('мм' if lang == 'rus' else 'mm')
        lines.append(f"{label}: {show(g['start'])}–{show(g['end'])}{count}")
    return '\n'.join(lines)
