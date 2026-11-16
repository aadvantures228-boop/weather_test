"""Защита пользователя от многократных нажатий и гонок состояний."""
import asyncio
import logging

from handlers import callbacks, messages
from config.texts import ui

logger = logging.getLogger(__name__)
_locks = {}


def _lock_for(user_id):
    lock = _locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[user_id] = lock
    return lock


async def button_callback(update, context):
    lock = _lock_for(update.effective_user.id)
    if lock.locked():
        try:
            await update.callback_query.answer('⏳ Уже обрабатывается / Processing…')
        except Exception:
            pass
        return
    async with lock:
        await callbacks.button_callback(update, context)


async def handle_reply(update, context):
    lock = _lock_for(update.effective_user.id)
    if lock.locked():
        await update.message.reply_text(ui('already_processing','rus'))
        return
    async with lock:
        await messages.handle_reply(update, context)
