from telegram import Update
from telegram.ext import CallbackContext
import storage
import utils
from config.emojis import *

async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    await storage.register_user(
        context, 
        user_id, 
        update.effective_user.username, 
        update.effective_user.first_name
    )
    
    lang = await storage.get_user_lang(context, user_id)
    
    from config.texts import ui
    text = ui('start', lang)

    # Главное меню зависит от прав администратора.
    from config.env import ADMIN_ID
    keyboard = utils.create_main_keyboard(user_id, ADMIN_ID, lang)
    await update.message.reply_text(text, reply_markup=keyboard)

async def settings(update: Update, context: CallbackContext):
    from handlers import settings as settings_module
    await settings_module.show_settings_menu(update, context)


async def favourites(update: Update, context: CallbackContext):
    from handlers import messages
    await messages.favorites(update, context)


async def weather(update: Update, context: CallbackContext):
    from handlers import messages
    await messages.get_weather_for_region(update, context)


async def compare(update: Update, context: CallbackContext):
    from handlers.features.compare import start_compare
    await start_compare(update, context)


async def cancel(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    lang = await storage.get_user_lang(context, user_id)
    
    # Сбрасываем состояния (эта функция синхронная, await не нужен)
    storage.reset_user_input_states(context, user_id)
    from handlers import admin
    admin.clear_direct_action(context)
    admin_was_active = False
    for key in ('admin_awaiting_broadcast', 'admin_awaiting_user_id', 'admin_awaiting_user_message'):
        if context.bot_data.get(key) == user_id:
            admin_was_active = True
            context.bot_data.pop(key, None)
    if admin_was_active:
        context.bot_data.pop('admin_target_user_id', None)
    
    await update.message.reply_text(
        f"{CROSS} Все процессы отменены." if lang == "rus" else f"{CROSS} All processes cancelled."
    )