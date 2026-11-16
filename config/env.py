"""Секреты только из переменных окружения или локального .env (НЕ коммитить)."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / '.env')
BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
WEATHER_TOKEN = os.getenv('WEATHER_TOKEN', '').strip()
BETTER_WEATHER_TOKEN = os.getenv('BETTER_WEATHER_TOKEN', '').strip()
DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
ADMIN_ID = int(os.getenv('ADMIN_ID', '0') or 0)
ADV_ACTIVATION_KEYS = tuple(k.strip().upper() for k in os.getenv('ADV_ACTIVATION_KEYS', '').split(',') if k.strip())
