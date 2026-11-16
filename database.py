import asyncpg
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool = None
    
    async def create_pool(self):
        try:
            self.pool = await asyncpg.create_pool(
                self.dsn,
                min_size=2,
                max_size=10
            )
            logger.info("Подключение к PostgreSQL успешно!")
            await self.create_tables()
        except Exception as e:
            logger.error(f"Ошибка подключения к PostgreSQL: {e}")
            raise
    
    async def close(self):
        if self.pool:
            await self.pool.close()
            logger.info("Подключение к PostgreSQL закрыто")
    
    async def create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    language VARCHAR(10) DEFAULT 'rus',
                    level VARCHAR(20) DEFAULT 'free',
                    region VARCHAR(255),
                    favorites JSONB DEFAULT '[]'::jsonb,
                    favorite_compares JSONB DEFAULT '[]'::jsonb,
                    settings JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS favorite_compares JSONB NOT NULL DEFAULT '[]'::jsonb")
            logger.info("Таблица users создана/проверена")
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_users_last_active 
                ON users(last_active)
            ''')
    
    async def register_user(self, user_id: int, username: str = None, first_name: str = None):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO users (user_id, username, first_name, last_active)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (user_id) 
                DO UPDATE SET 
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_active = NOW()
            ''', user_id, username, first_name)
    
    async def get_user(self, user_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
    
    async def update_user_field(self, user_id: int, field: str, value):
        # Имя колонки нельзя параметризовать в SQL: разрешаем только колонки users.
        allowed = {'username', 'first_name', 'language', 'level', 'region',
                   'favorites', 'favorite_compares', 'settings', 'last_active'}
        if field not in allowed:
            raise ValueError('Unknown user field')
        async with self.pool.acquire() as conn:
            # Для JSON полей явно конвертируем в строку
            if field in ['favorites', 'favorite_compares', 'settings']:
                value = json.dumps(value, ensure_ascii=False)
            await conn.execute(
                f'UPDATE users SET {field} = $1 WHERE user_id = $2',
                value, user_id
            )
    
    async def get_user_lang(self, user_id: int) -> str:
        user = await self.get_user(user_id)
        if not user:
            return 'rus'
        return user.get('language', 'rus') or 'rus'
    
    async def get_user_level(self, user_id: int) -> str:
        user = await self.get_user(user_id)
        if not user:
            return 'free'
        return user.get('level', 'free') or 'free'
    
    async def get_user_region(self, user_id: int):
        user = await self.get_user(user_id)
        return user.get('region') if user else None
    
    async def get_user_favorites(self, user_id: int) -> list:
        user = await self.get_user(user_id)
        if not user:
            return []
        favorites = user.get('favorites')
        # Если приходит строка, парсим её в список
        if isinstance(favorites, str):
            try:
                favorites = json.loads(favorites)
            except:
                favorites = []
        return favorites if favorites else []
    
    async def get_user_comparisons(self, user_id: int) -> list:
        user = await self.get_user(user_id)
        if not user:
            return []
        pairs = user.get('favorite_compares') or []
        if isinstance(pairs, str):
            try:
                pairs = json.loads(pairs)
            except (TypeError, ValueError):
                return []
        return pairs if isinstance(pairs, list) else []

    async def get_user_settings(self, user_id: int) -> dict:
        user = await self.get_user(user_id)
        if not user:
            return {}
        settings = user.get('settings')
        # Если приходит строка, парсим её в словарь
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except:
                settings = {}
        return settings if settings else {}
    
    async def add_favorite(self, user_id: int, city: str) -> bool:
        # Старый публичный метод оставлен для совместимости с предыдущими версиями.
        # Проверка уникальности теперь в одном месте по географическому ID.
        from favorites import add
        return await add(self, user_id, city)

    async def remove_favorite(self, user_id: int, city: str) -> bool:
        from favorites import remove
        return await remove(self, user_id, city)

    async def clear_favorites(self, user_id: int):
        await self.update_user_field(user_id, 'favorites', [])
    
    async def get_all_users(self):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('SELECT * FROM users')
            return {row['user_id']: dict(row) for row in rows}
    
    async def set_user_setting(self, user_id: int, key: str, value):
        settings = await self.get_user_settings(user_id)
        settings[key] = value
        await self.update_user_field(user_id, 'settings', settings)
        if key == 'language':
            await self.update_user_field(user_id, 'language', value)