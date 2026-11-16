"""OpenWeather: бесплатная текущая погода + общий кэш One Call 4.0 (TTL 30 мин)."""
import logging
import threading
import time
from datetime import timezone, datetime
from urllib.parse import urlparse, quote
import re

import requests

from config.env import WEATHER_TOKEN, BETTER_WEATHER_TOKEN
from config.geography import AMBIGUOUS_CITIES, COUNTRY_NAMES
from config.emojis import GLOBE, CROSS
from weather_format import current_text, local_datetime
from weather_format import description as weather_description

logger = logging.getLogger(__name__)
PAID_TTL_SECONDS = 30 * 60
GEO_TTL_SECONDS = 24 * 60 * 60
CURRENT_TTL_SECONDS = 120


class _SharedCache:
    """Потокобезопасный TTL кэш: один HTTP-запрос на один ключ одновременно."""

    def __init__(self):
        self._values = {}
        self._inflight = {}
        self._lock = threading.Lock()

    def invalidate(self, key):
        with self._lock:
            self._values.pop(key, None)

    def get_or_load(self, key, ttl, loader):
        while True:
            with self._lock:
                saved = self._values.get(key)
                if saved and saved[0] > time.monotonic():
                    return saved[1]
                event = self._inflight.get(key)
                if event is None:
                    event = threading.Event()
                    self._inflight[key] = event
                    is_owner = True
                else:
                    is_owner = False
            if not is_owner:
                event.wait(timeout=40)
                continue
            try:
                result = loader()
                if result is not None:
                    with self._lock:
                        if len(self._values) > 2000:
                            current = time.monotonic()
                            self._values = {k: v for k, v in self._values.items() if v[0] > current}
                            if len(self._values) > 4000:
                                self._values.clear()
                        self._values[key] = (time.monotonic() + ttl, result)
                return result
            finally:
                with self._lock:
                    self._inflight.pop(key, None)
                    event.set()


_cache = _SharedCache()


def _json(url, params):
    response = requests.get(url, params=params, timeout=12)
    response.raise_for_status()
    return response.json()


def get_country_name(code: str, lang: str='rus') -> str:
    return COUNTRY_NAMES.get(code, {}).get(lang, code)


def translate_weather_desc(desc_en: str, lang: str) -> str:
    """Совместимость со старым интерфейсом перевода описаний."""
    return weather_description(desc_en, lang)


def is_russian_city(city_name: str) -> bool:
    return any('а' <= c.lower() <= 'я' or c.lower() == 'ё' for c in (city_name or ''))


def valid_city_input(city: str) -> bool:
    """Ограничиваем мусорный ввод, сохраняя реальные имена с цифрами/дефисами."""
    if not isinstance(city, str):
        return False
    value = city.strip()
    if not 1 <= len(value) <= 100 or not any(ch.isalpha() for ch in value):
        return False
    if any(ord(ch) < 32 or ch in '<>{}\\/\u202e\u202d' for ch in value):
        return False
    return all(ch.isalnum() or ch.isspace() or ch in "-.,'’()" for ch in value)


def _geo(city):
    if not valid_city_input(city):
        return None
    query = AMBIGUOUS_CITIES.get(city.casefold().strip(), city.strip())
    key = ('geo', query.casefold())
    def load():
        data = _json('https://api.openweathermap.org/geo/1.0/direct',
                     {'q': query, 'limit': 1, 'appid': WEATHER_TOKEN})
        return data[0] if data else None
    try:
        return _cache.get_or_load(key, GEO_TTL_SECONDS, load)
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning('Геокодер: ошибка (%s)', type(exc).__name__)
        return None


def get_city_identity(city: str):
    """Каноническая идентичность города для избранного (без платного API)."""
    geo = _geo(city)
    if not geo or geo.get('lat') is None or geo.get('lon') is None:
        return None
    names = geo.get('local_names') or {}
    primary = str(geo.get('name') or city.strip())
    country = str(geo.get('country') or '').upper()
    lat, lon = round(float(geo['lat']), 4), round(float(geo['lon']), 4)
    return {
        'id': f'{country}:{lat:.4f}:{lon:.4f}',
        'name': primary, 'lat': lat, 'lon': lon, 'country': country,
        'state': geo.get('state'),
        'names': {'rus': str(names.get('ru') or primary),
                  'eng': str(names.get('en') or primary)}
    }


def region_is_valid(city):
    """True — найден, False — подтверждённо не найден, None — сбой сервиса.

    Это необходимо, чтобы админ-проверка не сбрасывала регионы при
    временных ошибках OpenWeather.
    """
    if not valid_city_input(city):
        return False
    query = AMBIGUOUS_CITIES.get(city.casefold().strip(), city.strip())
    try:
        response = _json('https://api.openweathermap.org/geo/1.0/direct',
                         {'q': query, 'limit': 1, 'appid': WEATHER_TOKEN})
        if not isinstance(response, list):
            return None
        return bool(response and isinstance(response[0], dict) and
                    response[0].get('lat') is not None and response[0].get('lon') is not None)
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return None


def same_city(city1: str, city2: str) -> bool:
    first, second = get_city_identity(city1), get_city_identity(city2)
    return bool(first and second and first['id'] == second['id'])


def get_coordinates(city: str):
    data = _geo(city)
    return (data.get('lat'), data.get('lon')) if data else (None, None)


def get_city_details(city_name: str, lang: str='rus'):
    data = _geo(city_name)
    code = data.get('country', '') if data else ''
    return {'country': get_country_name(code, lang) if code else ('Неизвестно' if lang == 'rus' else 'Unknown'),
            'country_code': code, 'state': data.get('state') if data else None}


def _current(city, lang='ru', force_refresh=False):
    identity = get_city_identity(city)
    if not identity:
        return None
    language = 'en' if lang == 'en' else 'ru'
    def load():
        return _json('https://api.openweathermap.org/data/2.5/weather',
                     {'lat': identity['lat'], 'lon': identity['lon'], 'appid': WEATHER_TOKEN,
                      'units': 'metric', 'lang': language})
    key = ('current', language, identity['id'])
    if force_refresh:
        _cache.invalidate(key)
    return _cache.get_or_load(key, CURRENT_TTL_SECONDS, load)


def get_weather_data(city: str, lang='rus', api_units='metric', settings=None, force_refresh=False):
    return get_weather_old_api(city, lang, api_units, settings, force_refresh=force_refresh)


def get_weather_old_api(city: str, lang='rus', api_units='metric', settings=None, force_refresh=False):
    # Название "old" сохранено ради совместимости: это ОСНОВНОЙ бесплатный endpoint.
    try:
        raw = _current(city, 'en' if lang == 'eng' else 'ru', force_refresh=force_refresh)
        if not raw or raw.get('cod') not in (None, 200, '200'):
            raise ValueError('Invalid weather response')
        from weather_format import effective_settings
        display = effective_settings(settings, api_units)
        identity = get_city_identity(city)
        if identity is None:
            raise ValueError('City is not verified')
        city_name = city.strip()  # оригинал для callback и геокодирования
        shown_city = identity['names'].get(lang) or identity['name']
        text = current_text(shown_city, raw, lang, display)
        return ({'city': city_name, 'temp': raw['main']['temp'],
                 'timezone': raw.get('timezone', 0),
                 'lat': raw.get('coord', {}).get('lat'), 'lon': raw.get('coord', {}).get('lon'),
                 'identity': identity['id'], 'display_city': shown_city,
                 'full_text': text, 'data': raw}, text)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else '?'
        logger.warning('Текущая погода: HTTP %s', status)
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        logger.warning('Ошибка текущей погоды: %s', type(exc).__name__)
    return None, (f'{CROSS} Не удалось получить погоду для «{city}». Проверьте город или попробуйте позже.'
                  if lang == 'rus' else f'{CROSS} Cannot load weather for {city}. Try later.')


def get_weather_one_call(lat, lon, city, lang='rus', api_units='metric', settings=None):
    """Совместимый интерфейс. Текущая погода теперь ВСЕГДА берётся бесплатно."""
    return get_weather_old_api(city, lang, api_units, settings)


def _paid_records(kind, lat, lon, count):
    if not BETTER_WEATHER_TOKEN:
        logger.warning('One Call 4.0 не настроен: BETTER_WEATHER_TOKEN отсутствует')
        return None
    coords = (round(float(lat), 4), round(float(lon), 4))
    key = ('onecall4', kind, coords)
    def load():
        base = f'https://api.openweathermap.org/data/4.0/onecall/timeline/{kind}'
        url = base
        params = {'lat': lat, 'lon': lon, 'appid': BETTER_WEATHER_TOKEN,
                  'units': 'metric', 'lang': 'en'}
        rows, seen = [], set()
        tz_offset, tz_name = 0, None
        for page in range(3 if kind == '1h' else 1):
            # 1h: запрашиваем только 20 точек, далее используется бесплатный 3h.
            response = _json(url, params)
            rows.extend(response.get('data') or [])
            tz_offset = response.get('timezone_offset', tz_offset)
            tz_name = response.get('timezone', tz_name)
            if len(rows) >= count:
                break
            next_url = response.get('next')
            parsed = urlparse(next_url or '')
            if not next_url or parsed.scheme != 'https' or parsed.netloc != 'api.openweathermap.org' or not parsed.path.endswith('/' + kind) or next_url in seen:
                break
            seen.add(next_url)
            url, params = next_url, {}  # URL от API уже содержит параметры
        if not rows:
            return None
        unique = {r['dt']: r for r in rows if isinstance(r, dict) and 'dt' in r}
        return {'rows': [unique[t] for t in sorted(unique)[:count]],
                'offset': tz_offset, 'timezone': tz_name}
    try:
        return _cache.get_or_load(key, PAID_TTL_SECONDS, load)
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        # Не выводим URL: в нём может находиться ключ OpenWeather.
        logger.warning('One Call 4.0 %s: %s', kind, type(exc).__name__)
        return None


def get_hourly_forecast(lat, lon, timezone_offset, days=2, lang='rus'):
    data = _paid_records('1h', lat, lon, 20)
    if not data:
        return None
    result = []
    for h in data['rows'][:max(0, min(int(days), 2))*24]:
        dt = local_datetime(h['dt'], data['offset'], data['timezone'])
        weather = h.get('weather') or [{}]
        description = weather_description(weather[0], lang)
        result.append({'time': dt.strftime('%H:%M'), 'datetime': dt,
                       'temp': h.get('temp'), 'feels_like': h.get('feels_like'),
                       'desc': description.capitalize(),
                       'rain': (h.get('rain') or {}).get('1h', 0) or 0,
                       'snow': (h.get('snow') or {}).get('1h', 0) or 0,
                       'pop': round((h.get('pop') or 0)*100, 1),
                       'weather_id': (weather[0].get('id') or 0), 'step_hours': 1})
    return result



def get_three_hour_forecast(lat, lon, lang='rus'):
    """Бесплатный прогноз на 5 дней с шагом 3 часа (40 точек).

    Кэшируем сырые записи на 30 минут; русское/английское описание
    формируем из официальных weather ID отдельно для каждого пользователя.
    """
    coords = (round(float(lat), 4), round(float(lon), 4))
    def load():
        return _json('https://api.openweathermap.org/data/2.5/forecast',
                     {'lat': lat, 'lon': lon, 'appid': WEATHER_TOKEN, 'units': 'metric', 'lang': 'en'})
    try:
        data = _cache.get_or_load(('free3h', coords), PAID_TTL_SECONDS, load)
        if not isinstance(data, dict):
            return None
        offset = (data.get('city') or {}).get('timezone', 0)
        result = []
        for h in data.get('list') or []:
            weather = h.get('weather') or [{}]
            result.append({'datetime': local_datetime(h['dt'], offset),
                           'time': local_datetime(h['dt'], offset).strftime('%H:%M'),
                           'temp': (h.get('main') or {}).get('temp'),
                           'desc': weather_description(weather[0], lang).capitalize(),
                           'rain': float((h.get('rain') or {}).get('3h') or 0),
                           'snow': float((h.get('snow') or {}).get('3h') or 0),
                           'weather_id': weather[0].get('id') or 0,
                           'pop': round((h.get('pop') or 0)*100, 1), 'step_hours': 3})
        return result
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        logger.warning('Бесплатный прогноз на 5 дней: %s', type(exc).__name__)
        return None


def get_extended_hourly_forecast(lat, lon, timezone_offset=0, lang='rus'):
    """Первые 20 часовых точек из 4.0, потом бесплатные трёхчасовые.

    Никаких новых платных страниц. Если One Call временно недоступен,
    отображаем бесплатный прогноз, явно обозначая его шаг.
    """
    paid = get_hourly_forecast(lat, lon, timezone_offset, 2, lang) or []
    free = get_three_hour_forecast(lat, lon, lang) or []
    if not paid:
        return free or None
    if not free:
        return paid
    cutoff = paid[-1]['datetime'].timestamp() + 3600
    # Важно: трёхчасовой интервал заканчивается на dt, а не начинается с него.
    # Обрезаем пересекающийся отрезок, чтобы не дублировать часы или осадки.
    tail = []
    for sample in free:
        end = sample['datetime'].timestamp()
        start = end - 3 * 3600
        if end <= cutoff:
            continue
        item = dict(sample)
        if start < cutoff:
            share = (end - cutoff) / (end - start)
            item['rain'] *= share
            item['snow'] *= share
            item['interval_start'] = datetime.fromtimestamp(cutoff, tz=sample['datetime'].tzinfo)
        tail.append(item)
    return paid + tail


def get_daily_forecast(lat, lon, timezone_offset, days=8, lang='rus'):
    data = _paid_records('1day', lat, lon, 8)
    if not data:
        return None
    days_ru = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']
    days_en = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    full_ru = ['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье']
    full_en = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    months_ru = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря']
    months_en = ['January','February','March','April','May','June','July','August','September','October','November','December']
    result=[]
    for d in data['rows'][:max(0, min(int(days), 8))]:
        dt = local_datetime(d['dt'], data['offset'], data['timezone'])
        weather = d.get('weather') or [{}]
        desc = weather_description(weather[0], lang)
        temps = d.get('temp') or {}
        feels = d.get('feels_like') or {}
        result.append({'date': dt.strftime('%d.%m'),
                       'date_full': f'{dt.day} {(months_ru if lang == "rus" else months_en)[dt.month-1]}',
                       'day_short': (days_ru if lang == 'rus' else days_en)[dt.weekday()],
                       'day_full': (full_ru if lang == 'rus' else full_en)[dt.weekday()],
                       'local_date': dt.date(), 'timezone_offset': data['offset'],
                       'timezone_name': data['timezone'],
                       'temp_day': temps.get('day'), 'temp_min': temps.get('min'),
                       'temp_max': temps.get('max'), 'feels_like': feels.get('day'),
                       'desc': desc.capitalize(), 'pressure': d.get('pressure'),
                       'humidity': d.get('humidity'), 'wind_speed': d.get('wind_speed'),
                       'sunrise': d.get('sunrise'), 'sunset': d.get('sunset'),
                       'wind_deg': d.get('wind_deg'), 'wind_gust': d.get('wind_gust'),
                       'clouds': d.get('clouds')})
    return result


def get_rain_forecast(lat, lon, timezone_offset, lang='rus'):
    hours = get_extended_hourly_forecast(lat, lon, timezone_offset, lang)
    if hours is None:
        return None
    return [{'time': h['time'], 'amount': round(h['rain']+h['snow'],2)}
            for h in hours if h['rain']+h['snow']>0]



def _alert_language_key(alert_id):
    # У национальных агентств один сигнал иногда имеет два ID, .RU и .EN.
    # Группируем языковые копии, чтобы не делать и не показывать двойные запросы.
    return re.sub(r'\.(?:RU|EN)(?=[:.])', '.LANG', alert_id, flags=re.IGNORECASE)


def _select_alert_description(contents, lang):
    if isinstance(contents, str):
        return contents.strip()
    if not isinstance(contents, list):
        return ''
    preferred = ('ru', 'en') if lang == 'rus' else ('en', 'ru')
    for prefix in preferred:
        for item in contents:
            if isinstance(item, dict) and str(item.get('language', '')).lower().startswith(prefix):
                text = item.get('description') or ''
                if text.strip():
                    return text.strip()
    for item in contents:
        if isinstance(item, dict) and (item.get('description') or '').strip():
            return item['description'].strip()
    return ''


def get_weather_alerts(lat, lon, lang='rus'):
    """Возвращает подробные предупреждения 4.0 для всех пользователей.

    Пустой список = API ответил, предупреждений нет.
    None = сервис недоступен или не настроен. Результаты общие и кэшируются 30 мин.
    Подробности берутся с /onecall/alert/{id}, не показываем голые ID.
    """
    if lat is None or lon is None or not BETTER_WEATHER_TOKEN:
        return None
    coords = (round(float(lat), 4), round(float(lon), 4))

    def load_index():
        return _json('https://api.openweathermap.org/data/4.0/onecall/current',
                     {'lat': lat, 'lon': lon, 'appid': BETTER_WEATHER_TOKEN,
                      'units': 'metric', 'lang': 'en'})

    try:
        index = _cache.get_or_load(('alerts-index', coords), PAID_TTL_SECONDS, load_index)
        data = index.get('data', index) if isinstance(index, dict) else {}
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            return None
        raw_alerts = data.get('alerts') or index.get('alerts') or []
        if not isinstance(raw_alerts, list):
            return None
        tz_offset = index.get('timezone_offset', data.get('timezone_offset', 0))
        tz_name = index.get('timezone', data.get('timezone'))

        # Выбираем один ID на одно предупреждение, на предпочтительном языке.
        grouped = {}
        for item in raw_alerts:
            if isinstance(item, dict):
                alert_id = item.get('id')
            elif isinstance(item, str):
                alert_id = item
            else:
                continue
            if not alert_id:
                continue
            group = _alert_language_key(alert_id)
            preferred = '.RU' if lang == 'rus' else '.EN'
            if group not in grouped or (preferred in alert_id.upper() and preferred not in grouped[group][0].upper()):
                grouped[group] = (alert_id, item)
        if not grouped:
            return []
        results = []
        for alert_id, original in list(grouped.values())[:6]:
            def load_details(alert_id=alert_id):
                return _json('https://api.openweathermap.org/data/4.0/onecall/alert/' + quote(alert_id, safe=''),
                             {'appid': BETTER_WEATHER_TOKEN})
            try:
                if isinstance(original, dict) and original.get('description'):
                    full = original
                else:
                    full = _cache.get_or_load(('alert-detail', alert_id), PAID_TTL_SECONDS, load_details)
            except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
                logger.warning('Подробности штормового предупреждения недоступны: %s', type(exc).__name__)
                continue
            if not isinstance(full, dict):
                continue
            tags = full.get('tags') or []
            if not isinstance(tags, list):
                tags = []
            results.append({
                'event': full.get('event') or (tags[0] if tags else ('Предупреждение о непогоде' if lang == 'rus' else 'Weather alert')),
                'sender_name': full.get('sender_name') or ('Метеослужба' if lang == 'rus' else 'Weather agency'),
                'start': full.get('start'), 'end': full.get('end'),
                'description': _select_alert_description(full.get('description'), lang),
                'timezone_offset': tz_offset, 'timezone_name': tz_name,
            })
        return results if results else None
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        logger.warning('Ошибка получения штормовых предупреждений: %s', type(exc).__name__)
        return None
