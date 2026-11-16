"""Регрессии навигации, штормов, перевода и поведения ожидания."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Заглушки Telegram (поддержаны в комплекте test_pre_release.py).
from test_pre_release import FakeContext, FakeQuery, FakeUpdate
from handlers import callbacks, navigation, messages, settings
import storage
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from weather_format import wind_direction, current_text
from weather_format import description


class TranslationTests(unittest.TestCase):
    def test_rain_and_snow_and_official_condition_codes(self):
        self.assertEqual(description({'id':616,'description':'Rain and snow'},'rus'),'дождь со снегом')
        self.assertEqual(description({'description':'light rain and snow'},'rus'),'небольшой дождь со снегом')
        self.assertEqual(description({'id':502,'description':'heavy intensity rain'},'rus'),'сильный дождь')
        self.assertEqual(description({'id':800,'description':'clear sky'},'eng'),'clear sky')
        self.assertEqual(description({'id':741,'description':'fog'},'rus'),'туман')

    def test_wind_direction_full_words_and_boundaries(self):
        self.assertEqual(wind_direction(0),'северный')
        self.assertEqual(wind_direction(45),'северо-восточный')
        self.assertEqual(wind_direction(270),'западный')
        self.assertEqual(wind_direction(359),'северный')
        self.assertEqual(wind_direction(90,'eng'),'east')
        body=current_text('Москва',{'main':{'temp':10},'weather':[{'id':616,'description':'Rain and snow'}],
             'wind':{'deg':135,'speed':3},'clouds':{}},'rus',{'show_wind_direction':True})
        self.assertIn('дождь со снегом',body)
        self.assertIn('юго-восточный',body)
        self.assertNotIn('135°',body)


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ctx=FakeContext()
        self.query=FakeQuery('weather_Moscow')
        self.query.message.text='🌇 Избранное'
        self.query.message.reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Москва',callback_data='weather_Moscow')]])

    async def test_favorite_weather_hourly_pagination_back_skips_pages(self):
        q=self.query
        c=self.ctx
        weather=InlineKeyboardMarkup([[InlineKeyboardButton('↩ Назад',callback_data='favorites')]])
        hourly=InlineKeyboardMarkup([[InlineKeyboardButton('◀ Назад',callback_data='hourly_page_0_Moscow')],
                                     [InlineKeyboardButton('↩ Назад',callback_data='weather_Moscow')]])
        await navigation.edit(q,c,'Погода в Москве',reply_markup=weather)
        self.assertEqual(q.edits[-1][1].inline_keyboard[0][0].callback_data,'nav_back')
        q.data='hourly_Moscow'
        await navigation.edit(q,c,'Почасовая сводка 1/4',reply_markup=hourly)
        self.assertEqual(q.edits[-1][1].inline_keyboard[0][0].callback_data,'hourly_page_0_Moscow')
        self.assertEqual(q.edits[-1][1].inline_keyboard[1][0].callback_data,'nav_back')
        q.data='hourly_page_1_Moscow'
        await navigation.edit(q,c,'Почасовая сводка 2/4',reply_markup=hourly)
        async def lang(*args): return 'rus'
        async def region(*args): return None
        with patch.object(storage,'get_user_lang',lang),patch.object(storage,'get_user_region',region):
            q.data='nav_back'
            await callbacks.button_callback(FakeDispatchUpdate(q),c)
            self.assertEqual(q.message.text,'Погода в Москве')
            await callbacks.button_callback(FakeDispatchUpdate(q),c)
            self.assertEqual(q.message.text,'🌇 Избранное')
        self.assertEqual(c.user_data['_navigation'][navigation._key(q)]['history'],[])

    async def test_maintains_separate_history_for_each_message(self):
        other=FakeQuery('weather_Kazan');other.message.text='Сравнение'
        await navigation.edit(self.query,self.ctx,'Погода Москва')
        await navigation.edit(other,self.ctx,'Погода Казань')
        await navigation.back(self.query,self.ctx)
        self.assertEqual(self.query.message.text,'🌇 Избранное')
        self.assertEqual(other.message.text,'Погода Казань')
        await navigation.back(other,self.ctx)
        self.assertEqual(other.message.text,'Сравнение')

    async def test_settings_help_is_news_directly_and_back_returns_settings(self):
        q=self.query
        q.message.text='Главное меню настроек'
        async def lang(*args):return 'rus'
        with patch.object(storage,'get_user_lang',lang):
            await settings.show_help(FakeDispatchUpdate(q),self.ctx)
        self.assertIn('Новости',q.message.text)
        self.assertNotIn('инструкция',q.message.text.lower())
        self.assertNotIn('Личный контакт',q.message.text)
        self.assertEqual(q.edits[-1][1].inline_keyboard[-1][-1].callback_data,'nav_back')
        await navigation.back(q,self.ctx)
        self.assertEqual(q.message.text,'Главное меню настроек')

    async def test_settings_change_value_does_not_create_unwanted_history_frame(self):
        q=self.query;c=self.ctx
        q.message.text='Настройки вывода'
        await navigation.edit(q,c,'Температура — C')
        await navigation.edit(q,c,'Температура — F',remember=False)
        await navigation.back(q,c)
        self.assertEqual(q.message.text,'Настройки вывода')

    async def test_no_history_leaves_message_unchanged(self):
        q=self.query
        self.assertFalse(await navigation.back(q,self.ctx))
        self.assertEqual(q.message.text,'🌇 Избранное')


class FakeDispatchUpdate:
    def __init__(self,q):
        self.callback_query=q
        self.message=None
        self.effective_user=q.from_user


class PendingTests(unittest.IsolatedAsyncioTestCase):
    async def _route_and_count(self, callback):
        c=FakeContext();u=FakeUpdate(callback)
        log={}
        async def lang(*args):return 'rus'
        async def region(*args):return None
        async def stub(*args,**kwargs):log['called']=True
        with patch.object(storage,'get_user_lang',lang),patch.object(storage,'get_user_region',region),\
             patch.object(messages,'show_hourly_forecast',stub),patch.object(messages,'show_rain_forecast',stub):
            await callbacks.button_callback(u,c)
        return u,log

    async def test_hourly_from_weather_has_notice_but_pagination_does_not(self):
        u,log=await self._route_and_count('hourly_Moscow')
        self.assertTrue(log['called'])
        self.assertTrue(u.callback_query.message.sent)
        self.assertTrue(u.callback_query.message.sent[0].deleted)
        u,log=await self._route_and_count('hourly_page_1_Moscow')
        self.assertTrue(log['called'])
        self.assertFalse(u.callback_query.message.sent)

    async def test_rain_from_weather_has_notice_but_day_switch_does_not(self):
        u,log=await self._route_and_count('rain_Moscow')
        self.assertTrue(log['called'])
        self.assertTrue(u.callback_query.message.sent[0].deleted)
        u,log=await self._route_and_count('rain_tomorrow_Moscow')
        self.assertTrue(log['called'])
        self.assertFalse(u.callback_query.message.sent)
        u,log=await self._route_and_count('rain_today_Moscow')
        self.assertTrue(log['called'])
        self.assertFalse(u.callback_query.message.sent)


class AlertsPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_free_user_can_view_alerts(self):
        q=FakeQuery('alerts_Moscow');c=FakeContext()
        async def lang(*args):return 'rus'
        async def level(*args):return 'free'
        with patch.object(storage,'get_user_lang',lang), patch.object(storage,'get_user_level',level), \
             patch.object(messages,'get_coordinates',return_value=(55,37)), \
             patch.object(messages,'get_weather_alerts',return_value=[{
                 'event':'Сильный ветер','sender_name':'Метеослужба',
                 'start':None,'end':None,'description':'Ожидается сильный ветер'}]):
            await messages.show_weather_alerts(FakeDispatchUpdate(q),c,'Москва')
        self.assertIn('Сильный ветер',q.message.text)
        self.assertNotIn('Нет доступа',q.message.text)

    async def test_adv_user_sees_detailed_alert_without_id(self):
        q=FakeQuery('alerts_Moscow');c=FakeContext()
        async def lang(*args):return 'rus'
        async def level(*args):return 'adv'
        def detailed(*args):
            return [{'event':'Сильный ветер','sender_name':'МЧС','start':1763100000,'end':1763110000,
                     'description':'Ожидаются порывы ветра','timezone_offset':10800,'timezone_name':None}]
        with patch.object(storage,'get_user_lang',lang),patch.object(storage,'get_user_level',level),\
             patch.object(messages,'get_coordinates',return_value=(55,37)),\
             patch.object(messages,'get_weather_alerts',side_effect=detailed):
            await messages.show_weather_alerts(FakeDispatchUpdate(q),c,'Москва')
        self.assertIn('Сильный ветер',q.message.text)
        self.assertIn('Ожидаются порывы',q.message.text)
        self.assertNotIn('Alert ID',q.message.text)

if __name__=='__main__':unittest.main()
