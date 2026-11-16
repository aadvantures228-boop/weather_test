from handlers import navigation
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext
from telegram.error import BadRequest
try:
    from telegram.error import TelegramError
except ImportError:  # минимальные заглушки в офлайн-тестах
    TelegramError = Exception
from html import escape
from config.texts import ui
import storage
import utils
from config.emojis import *
from config.env import ADMIN_ID

logger = logging.getLogger(__name__)


async def admin_panel(update: Update, context: CallbackContext):
    query = update.callback_query if hasattr(update, 'callback_query') else None
    user_id = update.effective_user.id if update.message else query.from_user.id
    lang = await storage.get_user_lang(context, user_id)

    if user_id != ADMIN_ID:
        if lang == "rus":
            text = f"{CROSS} У вас нет доступа к админ-панели."
        else:
            text = f"{CROSS} You don't have access to admin panel."
        if update.message:
            await update.message.reply_text(text)
        elif query:
            await query.answer(text, show_alert=True)
        return

    if lang == "rus":
        text = ui('admin_menu',lang)
    else:
        text = ui('admin_menu',lang)

    keyboard = utils.create_admin_panel_keyboard(lang)

    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    elif query:
        try:
            await navigation.edit(query, context, text, reply_markup=keyboard, parse_mode="HTML")
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                logger.error(f"Error: {e}")


async def show_users_list(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)

    if user_id != ADMIN_ID:
        await query.answer(f"{CROSS} Нет доступа", show_alert=True)
        return

    all_users = await storage.get_all_users(context)
    
    if not all_users:
        text = f"{USERS_LIST} Пользователей пока нет." if lang == "rus" else f"{USERS_LIST} No users yet."
        keyboard = [[InlineKeyboardButton(f"{BACK} Назад" if lang == "rus" else f"{BACK} Back", callback_data="admin_panel")]]
        try:
            await navigation.edit(query, context, text, reply_markup=InlineKeyboardMarkup(keyboard))
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                logger.error(f"Error: {e}")
        return

    if lang == "rus":
        text = ui('admin_users',lang,count=len(all_users))
    else:
        text = ui('admin_users',lang,count=len(all_users))

    keyboard = utils.create_user_list_keyboard(all_users, lang)

    try:
        await navigation.edit(query, context, text, reply_markup=keyboard, parse_mode="HTML")
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.error(f"Error: {e}")


async def show_user_detail(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)
    data = query.data

    if user_id != ADMIN_ID:
        await query.answer(f"{CROSS} Нет доступа", show_alert=True)
        return

    target_id = int(data.split("_", 3)[3])
    return await _render_user_detail(query, context, target_id, lang)


async def _render_user_detail(query, context, target_id, lang):
    db = storage.get_db(context)
    if db:
        user_data = await db.get_user(target_id)
    else:
        user_data = None
    
    if not user_data:
        text = f"{CROSS} Пользователь не найден." if lang == "rus" else f"{CROSS} User not found."
        keyboard = [[InlineKeyboardButton(f"{BACK} Назад" if lang == "rus" else f"{BACK} Back", callback_data="admin_users_list")]]
        try:
            await navigation.edit(query, context, text, reply_markup=InlineKeyboardMarkup(keyboard))
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                logger.error(f"Error: {e}")
        return

    if lang == "rus":
        text = (f"{USER} <b>Пользователь {target_id}</b>\n\n"
                f"Имя: {escape(str(user_data.get('first_name') or 'Н/Д'))}\n"
                f"Username: @{escape(str(user_data.get('username') or 'Н/Д'))}\n"
                f"Язык: {user_data.get('language', 'rus')}\n"
                f"Уровень: {('ADV' if user_data.get('level') == 'adv' else 'Basic' if user_data.get('level') == 'free' else escape(str(user_data.get('level') or 'free')))}\n"
                f"Регион: {escape(str(user_data.get('region') or 'Не выбран'))}\n"
                f"Регистрация: {user_data.get('created_at', 'Н/Д')}\n"
                f"Активен: {user_data.get('last_active', 'Н/Д')}")
    else:
        text = (f"{USER} <b>User {target_id}</b>\n\n"
                f"Name: {escape(str(user_data.get('first_name') or 'N/A'))}\n"
                f"Username: @{escape(str(user_data.get('username') or 'N/A'))}\n"
                f"Language: {user_data.get('language', 'rus')}\n"
                f"Level: {('ADV' if user_data.get('level') == 'adv' else 'Basic' if user_data.get('level') == 'free' else escape(str(user_data.get('level') or 'free')))}\n"
                f"Region: {escape(str(user_data.get('region') or 'Not set'))}\n"
                f"Registered: {user_data.get('created_at', 'N/A')}\n"
                f"Last active: {user_data.get('last_active', 'N/A')}")

    keyboard = utils.create_user_detail_keyboard(target_id, lang)

    try:
        await navigation.edit(query, context, text, reply_markup=keyboard, parse_mode="HTML")
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.error(f"Error: {e}")


async def start_broadcast(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)

    if user_id != ADMIN_ID:
        await query.answer(f"{CROSS} Нет доступа", show_alert=True)
        return

    context.bot_data['admin_awaiting_broadcast'] = user_id
    
    text = ui('admin_broadcast_prompt', lang)

    try:
        await navigation.edit(query, context, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back'), callback_data='nav_back')]]), parse_mode="HTML")
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.error(f"Error: {e}")


async def start_broadcast_user(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    lang = await storage.get_user_lang(context, user_id)

    if user_id != ADMIN_ID:
        await query.answer(f"{CROSS} Нет доступа", show_alert=True)
        return

    context.bot_data['admin_awaiting_user_id'] = user_id
    
    text = ui('admin_legacy_message_prompt',lang)

    try:
        await navigation.edit(query, context, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back'), callback_data='nav_back')]]), parse_mode="HTML")
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.error(f"Error: {e}")

# Личные действия доступны только владельцу ADMIN_ID. Состояния хранятся
# в user_data конкретного администратора, не в общем bot_data.
def clear_direct_action(context):
    context.user_data.pop('admin_action', None)
    context.user_data.pop('admin_action_target', None)


async def _get_target(query, context, prefix):
    if query.from_user.id != ADMIN_ID:
        await query.answer('Нет доступа', show_alert=True)
        return None
    try:
        target_id = int((query.data or '')[len(prefix):])
        db = storage.get_db(context)
        if target_id <= 0 or not db or not await db.get_user(target_id):
            await query.answer('Пользователь не найден', show_alert=True)
            return None
        return target_id
    except (ValueError, TypeError):
        await query.answer('Неверный ID', show_alert=True)
        return None


async def start_user_action(update, context, action):
    query = update.callback_query
    prefix = 'admin_direct_message_' if action == 'message' else 'admin_promote_'
    target = await _get_target(query, context, prefix)
    if target is None:
        return
    lang = await storage.get_user_lang(context, query.from_user.id)
    # Новое личное действие отменяет старую форму рассылки того же администратора.
    for old in ('admin_awaiting_broadcast', 'admin_awaiting_user_id', 'admin_awaiting_user_message'):
        if context.bot_data.get(old) == query.from_user.id:
            context.bot_data.pop(old, None)
    context.bot_data.pop('admin_target_user_id', None)
    context.user_data['admin_action'] = action
    context.user_data['admin_action_target'] = target
    key = 'admin_message_prompt' if action == 'message' else 'admin_promote_prompt'
    back = InlineKeyboardMarkup([[InlineKeyboardButton(
        f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back'),
        callback_data=f'admin_user_detail_{target}')]])
    await navigation.edit(query, context, ui(key, lang, user_id=target),
                          reply_markup=back, parse_mode='HTML')


async def demote_user(update, context):
    query = update.callback_query
    target = await _get_target(query, context, 'admin_demote_')
    if target is None:
        return
    lang = await storage.get_user_lang(context, query.from_user.id)
    clear_direct_action(context)
    await storage.set_user_level(context, target, 'free')
    try:
        await context.bot.send_message(target, ui('admin_recipient_demoted', await storage.get_user_lang(context, target)))
    except TelegramError:
        logger.info('Пользователь недоступен для уведомления о смене уровня')
    await _render_user_detail(query, context, target, lang)


async def handle_direct_input(update, context, text, lang):
    """True — текст был обработан как сообщение/ключ для выбранного пользователя."""
    if update.effective_user.id != ADMIN_ID:
        return False
    action = context.user_data.get('admin_action')
    if action not in ('message', 'promote'):
        return False
    target = context.user_data.get('admin_action_target')
    db = storage.get_db(context)
    if not isinstance(target, int) or not db or not await db.get_user(target):
        clear_direct_action(context)
        await update.message.reply_text('Пользователь больше не найден.' if lang == 'rus' else 'User not found.')
        return True
    if action == 'promote':
        if storage.validate_activation_key(text) != 'adv':
            await update.message.reply_text(ui('admin_invalid_key',lang))
            return True
        await storage.set_user_level(context, target, 'adv')
        clear_direct_action(context)
        try:
            await context.bot.send_message(target, ui('admin_recipient_promoted', await storage.get_user_lang(context, target)))
        except TelegramError:
            logger.info('Не удалось уведомить пользователя о повышении')
        await update.message.reply_text(ui('admin_promoted',lang,user_id=target),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                f'{BACK} ' + ('Вернуться к пользователю' if lang == 'rus' else 'Back to user'),
                callback_data=f'admin_user_detail_{target}')]]))
        return True
    try:
        recipient_lang = await storage.get_user_lang(context, target)
        await context.bot.send_message(target, ui('admin_recipient_message', recipient_lang,
                                    message=escape(text)), parse_mode='HTML')
    except TelegramError:
        await update.message.reply_text(f'{CROSS} ' + (
            'Не удалось доставить сообщение (возможно, пользователь заблокировал бота).'
            if lang == 'rus' else 'Could not deliver the message (user may have blocked the bot).'))
        return True
    clear_direct_action(context)
    await update.message.reply_text(ui('admin_sent',lang,user_id=target),
         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
             f'{BACK} ' + ('Вернуться к пользователю' if lang == 'rus' else 'Back to user'),
             callback_data=f'admin_user_detail_{target}')]]))
    return True


async def handle_legacy_admin_input(update, context, text, lang):
    """Обратная совместимость с массовой рассылкой и ручным вводом ID."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return False
    # Обработка ID пользователя для рассылки
    if context.bot_data.get('admin_awaiting_user_id') == user_id:
        if text.lower() == "/cancel":
            context.bot_data.pop('admin_awaiting_user_id', None)
            await update.message.reply_text(
                f"{CROSS} Рассылка пользователю отменена." if lang == "rus" else f"{CROSS} User broadcast cancelled."
            )
            return True
        try:
            target_id = int(text)
            context.bot_data['admin_target_user_id'] = target_id
            context.bot_data.pop('admin_awaiting_user_id', None)
            context.bot_data['admin_awaiting_user_message'] = user_id
            await update.message.reply_text(
                f"{BROADCAST} Введите сообщение для пользователя {target_id}:\n\n/cancel для отмены"
                if lang == "rus" else
                f"{BROADCAST} Enter message for user {target_id}:\n\n/cancel to cancel"
            )
        except ValueError:
            await update.message.reply_text(
                f"{CROSS} Неверный ID. Введите число или /cancel:"
                if lang == "rus" else
                f"{CROSS} Invalid ID. Enter a number or /cancel:"
            )
        return True

    # Обработка сообщения для рассылки пользователю
    if context.bot_data.get('admin_awaiting_user_message') == user_id:
        if text.lower() == "/cancel":
            context.bot_data.pop('admin_awaiting_user_message', None)
            context.bot_data.pop('admin_target_user_id', None)
            await update.message.reply_text(
                f"{CROSS} Рассылка отменена." if lang == "rus" else f"{CROSS} Broadcast cancelled."
            )
            return True
        target_id = context.bot_data.get('admin_target_user_id')
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=ui('admin_recipient_message', await storage.get_user_lang(context,target_id), message=escape(text)),
                parse_mode="HTML"
            )
            context.bot_data.pop('admin_awaiting_user_message', None)
            context.bot_data.pop('admin_target_user_id', None)
            await update.message.reply_text(
                f"{CHECK} Сообщение отправлено пользователю {target_id}!"
                if lang == "rus" else
                f"{CHECK} Message sent to user {target_id}!"
            )
        except Exception as e:
            await update.message.reply_text(
                f"{CROSS} Не удалось доставить сообщение. Возможно, пользователь заблокировал бота."
                if lang == "rus" else
                f"{CROSS} Could not deliver the message. The user may have blocked the bot."
            )
        return True

    # Рассылка всем
    if context.bot_data.get('admin_awaiting_broadcast') == user_id:
        if text.lower() == "/cancel":
            context.bot_data.pop('admin_awaiting_broadcast', None)
            await update.message.reply_text(
                f"{CROSS} {'Рассылка отменена.' if lang == 'rus' else 'Broadcast cancelled.'}"
            )
            return True

        all_users = await storage.get_all_users(context)
        user_ids = list(all_users.keys())

        success_count = 0
        failed_count = 0

        for uid in user_ids:
            try:
                await context.bot.send_message(chat_id=uid, text=update.message.text)
                success_count += 1
            except Exception as e:
                failed_count += 1

        context.bot_data.pop('admin_awaiting_broadcast', None)

        if lang == "rus":
            result_text = f"{CHECK} Рассылка завершена!\nДоставлено: {success_count}\nОшибок: {failed_count}"
        else:
            result_text = f"{CHECK} Broadcast complete!\nDelivered: {success_count}\nErrors: {failed_count}"

        await update.message.reply_text(result_text)
        return True


    return False


async def confirm_user_check(update, context):
    """Двухшаговое подтверждение операции с сохранёнными регионами."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        return await query.answer('Нет доступа', show_alert=True)
    lang = await storage.get_user_lang(context, query.from_user.id)
    text = ('Проверить регионы всех пользователей? Будут сброшены только\n'
            'достоверно неверные города. Настройки, избранное и уровни не изменятся.'
            if lang == 'rus' else 'Check all saved regions? Only confirmed invalid cities will be cleared.')
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ ' + ('Проверить' if lang == 'rus' else 'Check'),
                              callback_data='admin_check_users_confirm')],
        [InlineKeyboardButton(f'{BACK} ' + ('Назад' if lang == 'rus' else 'Back'),
                              callback_data='admin_panel')]
    ])
    await navigation.edit(query, context, text, reply_markup=kb)


async def check_all_regions(update, context):
    """Регионы проверяем последовательно, не считаем сетевой сбой ошибкой города."""
    import asyncio
    from weather_api import region_is_valid
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        return await query.answer('Нет доступа', show_alert=True)
    lang = await storage.get_user_lang(context, query.from_user.id)
    db = storage.get_db(context)
    if db is None:
        return await navigation.edit(query, context, 'Нет подключения к базе данных.' if lang == 'rus' else 'Database unavailable.')
    users = await storage.get_all_users(context)
    pending = [(uid, str(item.get('region') or '').strip())
               for uid, item in users.items() if item.get('region')]
    await navigation.edit(query, context, '⏳ Проверяю регионы…' if lang == 'rus' else '⏳ Checking regions…',
                          reply_markup=InlineKeyboardMarkup([[
                              InlineKeyboardButton(f'{BACK} ' + ('В админку' if lang == 'rus' else 'Admin panel'), callback_data='admin_panel')]]))
    cleared = 0
    unknown = 0
    for uid, region in pending:
        verdict = await asyncio.to_thread(region_is_valid, region)
        if verdict is False:
            # Не перезаписать регион, если пользователь успел самостоятельно его изменить.
            if await db.get_user_region(uid) == region:
                await db.update_user_field(uid, 'region', None)
                cleared += 1
        elif verdict is None:
            unknown += 1
        await asyncio.sleep(1.05)  # не превышать типичный лимит геокодера
    text = (f'✅ Проверено регионов: {len(pending)}\n'
            f'🗑️ Сброшено неверных: {cleared}\n'
            f'⏭️ Не удалось проверить: {unknown}' if lang == 'rus' else
            f'✅ Regions checked: {len(pending)}\n'
            f'🗑️ Invalid regions cleared: {cleared}\n'
            f'⏭️ Could not verify: {unknown}')
    await navigation.edit(query, context, text, reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton(f'{BACK} ' + ('В админку' if lang == 'rus' else 'Admin panel'), callback_data='admin_panel')]]))
