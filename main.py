import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.error import NetworkError
from config.env import BOT_TOKEN, DATABASE_URL, WEATHER_TOKEN, BETTER_WEATHER_TOKEN
from handlers import commands, interaction
from database import Database
from config.emojis import WARNING

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
# httpx на INFO пишет полный URL Telegram API с токеном бота.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

# Создаем экземпляр БД
db = Database(DATABASE_URL)

async def post_init(application: Application):
    # Подключаем БД и сохраняем в context.bot_data, чтобы все файлы могли её использовать
    await db.create_pool()
    application.bot_data['db'] = db
    logger.info("Бот и база данных инициализированы!")

async def post_shutdown(application: Application):
    await db.close()
    logger.info("Бот остановлен")

async def error_handler(update, context):
    # Случайный обрыв getUpdates обрабатывается встроенным повтором PTB.
    # Он не вызван конкретной кнопкой и не должен порождать сообщение в чат.
    if isinstance(context.error, NetworkError) and update is None:
        logger.warning('Временный разрыв соединения Telegram (%s); polling переподключится.',
                       type(context.error).__name__)
        return
    logger.error('Необработанная ошибка Telegram: %s', type(context.error).__name__, exc_info=context.error)
    if update and getattr(update, 'effective_message', None):
        try:
            await update.effective_message.reply_text(f'{WARNING} Произошла ошибка. Попробуйте ещё раз позже.')
        except Exception:
            pass


def main():
    if not BOT_TOKEN or not DATABASE_URL or not WEATHER_TOKEN:
        raise RuntimeError('Заполните BOT_TOKEN, DATABASE_URL, WEATHER_TOKEN в .env')
    try:
        if not BETTER_WEATHER_TOKEN:
            logger.warning('One Call 4.0 не настроен: доступны бесплатные 3-часовые прогнозы, но не точные часовые и платные дневные данные')
        logger.info("Запуск погодного бота Release 1.1...")
        application = (Application.builder().token(BOT_TOKEN)
                       # Отдельные таймауты для long-polling и отправки сообщений.
                       .get_updates_connect_timeout(15)
                       .get_updates_read_timeout(30)
                       .get_updates_pool_timeout(10)
                       .connect_timeout(15)
                       .read_timeout(20)
                       .pool_timeout(10)
                       .concurrent_updates(16)
                       .post_init(post_init)
                       .post_shutdown(post_shutdown)
                       .build())
        
        application.add_handler(CommandHandler("start", commands.start))
        application.add_handler(CommandHandler("settings", commands.settings))
        application.add_handler(CommandHandler("favourites", commands.favourites))
        application.add_handler(CommandHandler("weather", commands.weather))
        application.add_handler(CommandHandler("compare", commands.compare))
        application.add_handler(CommandHandler("cancel", commands.cancel))
        
        application.add_handler(CallbackQueryHandler(interaction.button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, interaction.handle_reply))
        
        application.add_error_handler(error_handler)
        logger.info("Бот успешно запущен и готов к работе!")
        application.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
        raise

if __name__ == '__main__':
    main()