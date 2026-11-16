"""Избранное городов: географические ID вместо строк и мягкая миграция JSONB.

Старые записи-строки НЕ удаляются при ошибке геокодирования. В БД не
требуется менять схему: favorites по-прежнему JSONB-массив.
"""
import asyncio
import logging
from weather_api import get_city_identity

logger = logging.getLogger(__name__)
_locks = {}


def _lock(user_id):
    return _locks.setdefault(user_id, asyncio.Lock())


def _plain_name(entry, lang='rus'):
    if isinstance(entry, dict):
        names = entry.get('names') or {}
        return str(names.get(lang) or entry.get('name') or '')
    return str(entry)


def _same(entry, identity, city):
    if isinstance(entry, dict) and identity:
        return entry.get('id') == identity['id']
    # Точный fallback для нераспознанных устаревших записей.
    return _plain_name(entry).casefold().strip() == city.casefold().strip()


async def _resolve(city):
    return await asyncio.to_thread(get_city_identity, city)


async def _read_entries(db, user_id):
    raw = await db.get_user_favorites(user_id)
    if not isinstance(raw, list):
        return []
    normalized = []
    dirty = False
    seen = set()
    for item in raw:
        if isinstance(item, dict) and item.get('id') and item.get('name'):
            entry = item
        elif isinstance(item, str):
            resolved = await _resolve(item)
            if resolved:
                resolved['name'] = item  # сохранить привычный текст пользователя
                entry = resolved
                dirty = True
            else:
                entry = item  # не терять город, даже если API временно недоступен
        else:
            # Неизвестную запись не удаляем автоматически.
            entry = item
        fingerprint = (entry.get('id') if isinstance(entry, dict) else None) or f'raw:{str(entry).casefold()}'
        if fingerprint in seen:
            dirty = True
            continue
        seen.add(fingerprint)
        normalized.append(entry)
    if dirty:
        await db.update_user_field(user_id, 'favorites', normalized)
    return normalized


async def list_names(db, user_id, lang='rus'):
    async with _lock(user_id):
        return [_plain_name(e, lang) for e in await _read_entries(db, user_id)]


async def contains(db, user_id, city):
    identity = await _resolve(city)
    async with _lock(user_id):
        entries = await _read_entries(db, user_id)
        return any(_same(e, identity, city) for e in entries)


async def canonical_name(db, user_id, city, lang='rus'):
    identity = await _resolve(city)
    async with _lock(user_id):
        for entry in await _read_entries(db, user_id):
            if _same(entry, identity, city):
                return _plain_name(entry, lang)
    return city


async def add(db, user_id, city):
    identity = await _resolve(city)
    if not identity:
        return False
    async with _lock(user_id):
        entries = await _read_entries(db, user_id)
        if any(_same(e, identity, city) for e in entries) or len(entries) >= 15:
            return False
        identity['name'] = city
        entries.append(identity)
        await db.update_user_field(user_id, 'favorites', entries)
        return True


async def remove(db, user_id, city):
    identity = await _resolve(city)
    async with _lock(user_id):
        entries = await _read_entries(db, user_id)
        for idx, entry in enumerate(entries):
            if _same(entry, identity, city):
                del entries[idx]
                await db.update_user_field(user_id, 'favorites', entries)
                return True
        return False


async def clear(db, user_id):
    async with _lock(user_id):
        await db.update_user_field(user_id, 'favorites', [])


# === Избранные сравнения: независимый JSONB-список пар ===
"""Методы для сохранённых сравнений, отдельно от списка городов."""


_compare_locks = {}


def _compare_lock(user_id):
    return _compare_locks.setdefault(user_id, asyncio.Lock())


def _compare_name(info, lang):
    return str((info.get('names') or {}).get(lang) or info.get('name') or '')


def _compare_key(pair):
    try:
        return frozenset((pair['first']['id'], pair['second']['id']))
    except (KeyError, TypeError):
        return frozenset()


async def compare_list_pairs(db, user_id, lang='rus'):
    if db is None:
        return []
    values = await db.get_user_comparisons(user_id)
    if not isinstance(values, list):
        return []
    output = []
    for i, pair in enumerate(values):
        if not isinstance(pair, dict) or not _compare_key(pair) or len(_compare_key(pair)) != 2:
            continue
        a, b = pair['first'], pair['second']
        output.append({'index': i, 'first': _compare_name(a, lang), 'second': _compare_name(b, lang),
                       'first_id': a['id'], 'second_id': b['id'],
                       'first_coords': (a.get('lat'), a.get('lon')),
                       'second_coords': (b.get('lat'), b.get('lon'))})
    return output


async def compare_contains(db, user_id, first, second):
    if not db:
        return False
    a, b = await asyncio.gather(asyncio.to_thread(get_city_identity, first),
                                asyncio.to_thread(get_city_identity, second))
    if not a or not b:
        return False
    key = frozenset((a['id'], b['id']))
    values = await db.get_user_comparisons(user_id)
    return any(_compare_key(p) == key for p in (values or []))


async def compare_add(db, user_id, first, second):
    if not db:
        return False
    a, b = await asyncio.gather(asyncio.to_thread(get_city_identity, first),
                                asyncio.to_thread(get_city_identity, second))
    if not a or not b or a['id'] == b['id']:
        return False
    key = frozenset((a['id'], b['id']))
    async with _compare_lock(user_id):
        values = await db.get_user_comparisons(user_id)
        if not isinstance(values, list):
            values = []
        if len(values) >= 15 or any(_compare_key(p) == key for p in values):
            return False
        values.append({'first': a, 'second': b})
        await db.update_user_field(user_id, 'favorite_compares', values)
    return True


async def compare_remove(db, user_id, index):
    if not db:
        return False
    async with _compare_lock(user_id):
        values = await db.get_user_comparisons(user_id)
        if not isinstance(values, list) or not 0 <= index < len(values):
            return False
        del values[index]
        await db.update_user_field(user_id, 'favorite_compares', values)
    return True


async def compare_remove_pair(db, user_id, first, second):
    if not db:
        return False
    a, b = await asyncio.gather(asyncio.to_thread(get_city_identity, first),
                                asyncio.to_thread(get_city_identity, second))
    if not a or not b:
        return False
    key = frozenset((a['id'], b['id']))
    async with _compare_lock(user_id):
        values = await db.get_user_comparisons(user_id)
        if not isinstance(values, list):
            return False
        filtered = [pair for pair in values if _compare_key(pair) != key]
        if len(filtered) == len(values):
            return False
        await db.update_user_field(user_id, 'favorite_compares', filtered)
    return True

async def compare_clear(db, user_id):
    if db:
        async with _compare_lock(user_id):
            await db.update_user_field(user_id, 'favorite_compares', [])
