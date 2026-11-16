"""Регрессии исправления 15.11: меню настроек и страницы навигации."""
import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_pre_release import FakeContext, FakeQuery
from handlers import navigation, callbacks, settings
import storage
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class CallbackUpdate:
    def __init__(self, query):
        self.callback_query = query
        self.message = None
        self.effective_user = query.from_user


class SettingsAndNavigationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ctx = FakeContext()
        self.user_settings = {
            'temperature': 'celsius', 'pressure': 'mmhg',
            'time_format': '24h', 'wind_speed': 'ms',
            'language': 'rus', 'show_clouds': True,
            'show_wind_direction': True, 'show_sunrise_sunset': True,
            'show_wind_gust': True, 'show_extra_data_btn': True,
            'show_set_region_btn': True,
        }
        self.query = FakeQuery('settings_display')
        self.query.message.text = '⚙️ Главное меню настроек'
        self.query.message.reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton('Настройки вывода', callback_data='settings_display')
        ]])

        async def lang(*args):
            return self.user_settings.get('language', 'rus')
        async def region(*args):
            return None
        async def user_settings(*args):
            return dict(self.user_settings)
        async def set_value(context, user_id, key, value):
            self.user_settings[key] = value

        self.mocks = [
            patch.object(storage, 'get_user_lang', lang),
            patch.object(storage, 'get_user_region', region),
            patch.object(storage, 'get_user_settings', user_settings),
            patch.object(storage, 'set_user_setting', set_value),
        ]
        for p in self.mocks:
            p.start()
            self.addCleanup(p.stop)

    async def press(self, data):
        self.query.data = data
        await callbacks.button_callback(CallbackUpdate(self.query), self.ctx)
        return self.query.message.text

    async def test_display_opens_and_returns_to_settings_root(self):
        text = await self.press('settings_display')
        self.assertIn('Настройки вывода', text)
        self.assertEqual(self.query.message.reply_markup.inline_keyboard[-1][0].callback_data, 'nav_back')
        self.assertIn('Главное меню настроек', await self.press('nav_back'))

    async def test_choice_update_is_one_page_and_not_one_step_per_click(self):
        await self.press('settings_display')
        await self.press('settings_temp')
        await self.press('settings_set_temperature_fahrenheit')
        self.assertEqual(self.user_settings['temperature'], 'fahrenheit')
        await self.press('settings_set_temperature_celsius')
        self.assertEqual(self.user_settings['temperature'], 'celsius')
        self.assertIn('Настройки вывода', await self.press('nav_back'))
        self.assertIn('Главное меню настроек', await self.press('nav_back'))

    async def test_extra_toggle_does_not_create_history_page(self):
        await self.press('settings_display')
        self.assertIn('Дополнительные данные', await self.press('settings_extra_data'))
        await self.press('settings_toggle_extra_show_clouds')
        self.assertFalse(self.user_settings['show_clouds'])
        await self.press('settings_toggle_extra_show_clouds')
        self.assertTrue(self.user_settings['show_clouds'])
        self.assertIn('Настройки вывода', await self.press('nav_back'))
        self.assertIn('Главное меню настроек', await self.press('nav_back'))

    async def test_button_toggle_does_not_create_history_page(self):
        await self.press('settings_display')
        await self.press('settings_extra_buttons')
        await self.press('settings_toggle_button_show_set_region_btn')
        self.assertFalse(self.user_settings['show_set_region_btn'])
        self.assertIn('Настройки вывода', await self.press('nav_back'))

    async def test_all_settings_submenus_open_without_exception(self):
        await self.press('settings_display')
        for menu, expected in (
            ('settings_pressure', 'Давление'),
            ('settings_time', 'Формат времени'),
            ('settings_wind', 'Скорость ветра'),
            ('settings_extra_data', 'Дополнительные данные'),
            ('settings_extra_buttons', 'Дополнительные кнопки'),
        ):
            self.assertIn(expected, await self.press(menu))
            self.assertIn('Настройки вывода', await self.press('nav_back'))
        self.assertIn('Главное меню настроек', await self.press('nav_back'))

    async def test_language_switch_remains_one_page(self):
        await self.press('settings_language')
        await self.press('settings_set_language_eng')
        self.assertEqual(self.user_settings['language'], 'eng')
        self.assertIn('Language', self.query.message.text)
        self.assertIn('Главное меню настроек', await self.press('nav_back'))

    async def test_no_stored_settings_uses_defaults(self):
        self.user_settings.clear()
        self.assertIn('Настройки вывода', await self.press('settings_display'))
        self.assertIn('°C', self.query.message.reply_markup.inline_keyboard[0][0].text)

    async def test_different_screens_have_separate_history_per_message(self):
        other = FakeQuery('settings_display')
        other.message.text = 'Другое главное меню настроек'
        await self.press('settings_display')
        await navigation.edit(other, self.ctx, 'Настройки вывода')
        await self.press('nav_back')
        self.assertIn('Главное меню настроек', self.query.message.text)
        self.assertEqual(other.message.text, 'Настройки вывода')

    async def test_hourly_pages_and_rain_days_skip_actions(self):
        q = self.query
        q.data = 'weather_Moscow'
        await navigation.edit(q, self.ctx, 'Погода в Москве')
        q.data = 'hourly_Moscow'
        await navigation.edit(q, self.ctx, 'Часы 1/4')
        for page in range(1, 4):
            q.data = f'hourly_page_{page}_Moscow'
            await navigation.edit(q, self.ctx, f'Часы {page + 1}/4')
        self.assertEqual(len(self.ctx.user_data['_navigation'][navigation._key(q)]['history']), 2)
        self.assertTrue(await navigation.back(q, self.ctx))
        self.assertEqual(q.message.text, 'Погода в Москве')

        q.data = 'rain_Moscow'
        await navigation.edit(q, self.ctx, 'Дождь сегодня')
        q.data = 'rain_tomorrow_Moscow'
        await navigation.edit(q, self.ctx, 'Дождь завтра')
        q.data = 'rain_today_Moscow'
        await navigation.edit(q, self.ctx, 'Дождь сегодня')
        self.assertTrue(await navigation.back(q, self.ctx))
        self.assertEqual(q.message.text, 'Погода в Москве')

    async def test_settings_special_routes_identity(self):
        self.assertEqual(navigation._page_id('settings_set_time_format_12h'),
                         'settings_choice:time_format')
        self.assertEqual(navigation._page_id('settings_set_language_eng'),
                         'settings_language')
        self.assertEqual(navigation._page_id('settings_toggle_extra_show_clouds'),
                         'settings_extra_data')
        self.assertEqual(navigation._page_id('hourly_page_4_Moscow'),
                         'hourly_forecast')


if __name__ == '__main__':
    unittest.main()
