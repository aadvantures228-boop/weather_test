"""Офлайн-проверки релиза: без Telegram, PostgreSQL и настоящих ключей API."""
import asyncio
import importlib
import sys
import threading
import time
import types
import unittest
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Заглушки Telegram только для локальных тестов; production использует PTB 20.7.
telegram = types.ModuleType('telegram')
telegram_ext = types.ModuleType('telegram.ext')
telegram_error = types.ModuleType('telegram.error')
class FakeButton:
    def __init__(self, text, callback_data=None): self.text=text; self.callback_data=callback_data
class FakeMarkup:
    def __init__(self, rows, **kw): self.inline_keyboard=rows
class FakeReplyMarkup:
    def __init__(self, rows, **kw): self.keyboard=rows
class BadRequest(Exception): pass
telegram.InlineKeyboardButton=FakeButton
telegram.InlineKeyboardMarkup=FakeMarkup
telegram.ReplyKeyboardMarkup=FakeReplyMarkup
telegram.Update=object
telegram_ext.CallbackContext=object
telegram_error.BadRequest=BadRequest
sys.modules.setdefault('telegram',telegram)
sys.modules.setdefault('telegram.ext',telegram_ext)
sys.modules.setdefault('telegram.error',telegram_error)

import weather_api as api
import weather_format as fmt
import storage
import utils
from handlers import callbacks, messages, settings


class Response:
    def __init__(self, data): self.data=data
    def raise_for_status(self): pass
    def json(self): return self.data


class FakeOpenWeather:
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()
        self.base = int(datetime.now(timezone.utc).timestamp())//3600*3600+3600
    def get(self, url, params=None, timeout=None):
        with self.lock: self.calls.append(url)
        if '/geo/1.0/direct' in url:
            return Response([{'lat':55.75,'lon':37.61,'country':'RU','state':'Москва'}])
        if '/data/2.5/forecast' in url:
            return Response({'city': {'timezone':10800}, 'list':[
                {'dt':self.base+(i*3)*3600,
                 'main':{'temp':12}, 'weather':[{'id':800,'description':'clear sky'}],
                 'rain':{'3h':1.0} if i==10 else {}}
                for i in range(1,41)]})
        if '/data/2.5/weather' in url:
            return Response({'cod':200, 'name':'Moscow','coord':{'lat':55.75,'lon':37.61},
               'timezone':10800, 'sys':{'sunrise': self.base, 'sunset':self.base+36000},
               'weather':[{'description':'ясно' if params.get('lang')=='ru' else 'clear sky'}],
               'main':{'temp':10,'feels_like':8,'humidity':75,'pressure':1000},
               'wind':{'speed':5,'deg':0,'gust':8},'clouds':{'all':0}})
        if '/timeline/1h' in url:
            idx = int(url.split('start=')[1].split('&')[0]) if 'start=' in url else 0
            start = idx*20
            entries = [{'dt':self.base+(start+i)*3600, 'temp':10+i*0.1,
                        'weather':[{'description':'clear sky'}],
                        'rain':{'1h':1.5} if i == 3 else {},'pop':0.1}
                       for i in range(min(20,48-start))]
            data = {'data':entries,'timezone_offset':10800,'timezone':'Europe/Moscow'}
            if start+20 < 48:
                data['next']='https://api.openweathermap.org/data/4.0/onecall/timeline/1h?start='+str(idx+1)+'&appid=TEST'
            return Response(data)
        if '/onecall/current' in url:
            return Response({'data':{'alerts':['TEST.ALERT.RU:123', 'TEST.ALERT.EN:123']},
                             'timezone_offset':10800,'timezone':'Europe/Moscow'})
        if '/onecall/alert/' in url:
            return Response({'sender_name':'Hydromet', 'event':'Сильный снег',
                'start':self.base, 'end':self.base+3600,
                'description':[{'language':'ru-RU','description':'Предупреждение на русском.'},
                               {'language':'en-GB','description':'Weather alert in English.'}],
                'tags':['Snow']})
        if '/timeline/1day' in url:
            entries = []
            now = datetime.now(timezone.utc).replace(hour=12, minute=0,second=0,microsecond=0)
            for i in range(8):
                entries.append({'dt':int((now+timedelta(days=i)).timestamp()),
                    'temp':{'day':12,'min':4,'max':15}, 'feels_like':{'day':10},
                    'weather':[{'description':'clear sky'}], 'sunrise':self.base,
                    'sunset':self.base+40000,'humidity':55,'pressure':1012,
                    'wind_speed':5,'wind_deg':0,'clouds':0})
            return Response({'data':entries,'timezone_offset':10800,'timezone':'Europe/Moscow'})
        raise AssertionError('Unexpected network URL: '+url.split('?')[0])


class FakeMessage:
    next_id=100
    def __init__(self, text=''):
        self.text=text; self.edits=[]; self.sent=[]; self.deleted=False
        self.message_id=FakeMessage.next_id
        FakeMessage.next_id+=1
        self.chat_id=123
        self.reply_markup=None
    async def reply_text(self, text, **kw):
        message=FakeMessage(text); message.reply_markup=kw.get('reply_markup')
        self.sent.append(message)
        return message
    async def delete(self): self.deleted=True


class FakeQuery:
    def __init__(self, data=''):
        self.data=data; self.from_user=types.SimpleNamespace(id=123)
        self.message=FakeMessage()
        self.edits=[]; self.answer_count=0
    async def answer(self, *args,**kw): self.answer_count+=1
    async def edit_message_text(self,text,**kw):
        self.edits.append((text,kw.get('reply_markup')))
        self.message.text=text
        self.message.reply_markup=kw.get('reply_markup')
    async def edit_message_reply_markup(self,**kw):
        self.edits.append(('',kw.get('reply_markup')))
        self.message.reply_markup=kw.get('reply_markup')


class FakeContext:
    def __init__(self):
        self.user_data={}; self.bot_data={}
        self.bot=types.SimpleNamespace(send_message=self.send_message)
    async def send_message(self,**kw):return FakeMessage()


class FakeUpdate:
    def __init__(self,data=None,text=None):
        self.callback_query=FakeQuery(data) if data is not None else None
        self.message=FakeMessage(text) if text is not None else None
        self.effective_user=types.SimpleNamespace(id=123,username='tester',first_name='Test')


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.provider=FakeOpenWeather()
        self.patcher=patch('weather_api.requests.get',self.provider.get)
        self.patcher.start()
        api._cache=api._SharedCache()
        api.WEATHER_TOKEN='FREE-TEST'; api.BETTER_WEATHER_TOKEN='PAID-TEST'
    def tearDown(self): self.patcher.stop()
    def paid(self):return [u for u in self.provider.calls if '/data/4.0/' in u]

    def test_current_is_free_and_settings_apply(self):
        s={'temperature':'fahrenheit','pressure':'hpa','wind_speed':'kmh',
           'time_format':'12h','show_clouds':False,'show_wind_direction':False,
           'show_wind_gust':False,'show_sunrise_sunset':False}
        info,text=api.get_weather_data('Moscow','rus','metric',s)
        self.assertIsNotNone(info)
        self.assertIn('50°F',text)
        self.assertIn('18.0 км/ч',text)
        self.assertIn('1000 hPa',text)
        for word in ('Облачность','Направление','Порывы','Восход','Закат'):
            self.assertNotIn(word,text)
        self.assertEqual(len(self.paid()),0)
        before=len(self.provider.calls)
        api.get_weather_data('Moscow','rus','metric',s)
        self.assertEqual(len(self.provider.calls),before)

    def test_paid_hourly_cache_shared_with_rain_and_languages(self):
        h=api.get_hourly_forecast(55.75,37.61,0,2,'rus')
        self.assertEqual(len(h),20)
        self.assertEqual(len(self.paid()),1)
        self.assertEqual(h[0]['datetime'].utcoffset(),timedelta(hours=3))
        api.get_rain_forecast(55.75,37.61,0,'eng')
        api.get_hourly_forecast(55.75,37.61,0,2,'eng')
        self.assertEqual(len(self.paid()),1)
        self.assertEqual(api.get_hourly_forecast(55.75,37.61,0,1,'eng')[0]['desc'],'Clear sky')

    def test_paid_daily_shared_across_users(self):
        a=api.get_daily_forecast(55.75,37.61,0,8,'rus')
        b=api.get_daily_forecast(55.75,37.61,0,7,'eng')
        self.assertEqual(len(a),8)
        self.assertEqual(len(b),7)
        self.assertEqual(len(self.paid()),1)
        self.assertEqual(a[0]['day_short'],['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][a[0]['local_date'].weekday()])

    def test_concurrent_users_one_paid_fetch(self):
        def get():return api.get_daily_forecast(55.75,37.61,0,8,'eng')
        with ThreadPoolExecutor(max_workers=12) as executor:
            all_results=list(executor.map(lambda _:get(),range(12)))
        self.assertEqual(len(self.paid()),1)
        self.assertTrue(all(len(x)==8 for x in all_results))

    def test_alerts_are_detailed_deduplicated_and_cached(self):
        first=api.get_weather_alerts(55.75,37.61,'rus')
        self.assertEqual(len(first),1)
        self.assertEqual(first[0]['event'],'Сильный снег')
        self.assertIn('на русском',first[0]['description'])
        self.assertEqual(len(self.paid()),2)  # index + one detailed alert, not RU+EN
        english=api.get_weather_alerts(55.75,37.61,'eng')
        self.assertEqual(len(english),1)
        self.assertIn('English',english[0]['description'])
        self.assertEqual(len(self.paid()),3)  # different language alert detail once

    def test_alerts_empty_and_not_available(self):
        with patch.object(api,'_json',lambda u,p: {'data':{'alerts':[]}}):
            self.assertEqual(api.get_weather_alerts(1,2),[])
        api.BETTER_WEATHER_TOKEN=''
        self.assertIsNone(api.get_weather_alerts(3,4))


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_minutely_and_callbacks_within_64_bytes(self):
        city='Очень-Длинное-Название-Населённого-Пункта-'*5
        markup=utils.create_weather_keyboard(city,False,None,settings={})
        callbacks_=[button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertFalse(any('minutely' in c for c in callbacks_))
        self.assertTrue(all(len(x.encode())<=64 for x in callbacks_))
        for value in callbacks_:
            if value.startswith('hourly_'):
                self.assertEqual(utils.decode_city(value[len('hourly_'):]),city)

    async def test_favorites_navigation_and_old_rain_callback(self):
        c=FakeContext(); q=FakeQuery('rain_tomorrow_fav_fav_0')
        c.user_data['fav_map']={'fav_0':'Moscow'}
        city, fav, safe, compare=await callbacks._source('fav_fav_0', c, q, 123)
        self.assertEqual((city,fav,safe,compare),('Moscow',True,'fav_0',False))
        city, fav, safe, compare=await callbacks._source('cmp_New_York', c,q,123)
        self.assertEqual((city,fav,safe,compare),('New York',False,None,True))

    async def test_settings_help_is_short_and_no_old_username(self):
        c=FakeContext(); u=FakeUpdate('settings_help')
        async def lang(*args):return 'rus'
        with patch.object(storage,'get_user_lang',lang):
            await settings.show_help(u,c)
            await settings.show_help_info(u,c)
        help_text=u.callback_query.edits[0][0]
        info_text=u.callback_query.edits[1][0]
        self.assertIn('<b>Новости</b>',help_text)
        self.assertIn('weather_worldmap',help_text)
        self.assertNotIn('инструкция',help_text.lower())
        self.assertNotIn('обратная связь',info_text.lower())
        self.assertNotIn('контакт поддержки',info_text.lower())
        self.assertNotIn('apchi10',info_text)

    async def test_region_changed_through_settings_input(self):
        u=FakeUpdate(text='Moscow'); c=FakeContext()
        c.user_data['awaiting_region_from_settings']=True
        s={}
        async def lang(*args):return 'rus'
        async def none(*args):return None
        async def user_settings(*args):return {'show_clouds':False}
        async def false(*args):return False
        async def changed(*args):s['region']=args[-1]
        def fake_weather(city, lang, units, settings):
            self.assertFalse(settings['show_clouds'])
            return {'city':city,'temp':10},'Тестовая погода'
        with patch.object(storage,'get_user_lang',lang),patch.object(storage,'get_user_region',none),\
             patch.object(storage,'register_user',none),patch.object(storage,'get_user_settings',user_settings),\
             patch.object(storage,'get_api_units',lang),patch.object(storage,'set_user_region',changed),\
             patch.object(storage,'is_city_in_favorites',false),patch.object(messages,'get_weather_data',fake_weather):
            await messages.handle_reply(u,c)
        self.assertEqual(s['region'],'Moscow')
        self.assertFalse(c.user_data['awaiting_region_from_settings'])
        self.assertTrue(u.message.sent)

    async def test_hourly_button_routes_from_favorites(self):
        c=FakeContext(); u=FakeUpdate('hourly_fav_0')
        c.user_data['fav_map']={'fav_0':'Moscow'}
        called={}
        async def lang(*args):return 'rus'
        async def region(*args):return None
        async def level(*args):return 'free'
        async def stub(*args,**kw):called['args']=args;called['kw']=kw
        with patch.object(storage,'get_user_lang',lang),patch.object(storage,'get_user_region',region),\
             patch.object(storage,'get_user_level',level),patch.object(messages,'show_hourly_forecast',stub):
            await callbacks.button_callback(u,c)
        self.assertEqual(called['args'][2],'Moscow')
        self.assertTrue(called['args'][4])
        self.assertEqual(called['args'][5],'fav_0')
        self.assertTrue(u.callback_query.message.sent[0].deleted)

    async def test_important_callback_routes(self):
        c=FakeContext()
        c.user_data['fav_map']={'fav_0':'Moscow'}
        calls=[]
        async def lang(*args):return 'rus'
        async def none(*args):return None
        async def stub(*args,**kwargs):
            calls.append((args,kwargs))
        paths = [
            ('settings_temp',settings.show_setting_choice),
            ('settings_set_temperature_fahrenheit',settings.set_setting_value),
            ('settings_toggle_extra_show_clouds',settings.toggle_extra_setting),
            ('settings_toggle_button_show_extra_data_btn',settings.toggle_button_setting),
            ('settings_change_region',settings.start_region_change),
            ('week_forecast_fav_0',messages.show_week_forecast),
            ('day_forecast_fav_0_1',messages.show_day_forecast),
            ('week_summary_fav_0',messages.show_week_summary),
            ('week_summary_tomorrow_fav_0',messages.show_week_summary_tomorrow),
            ('rain_tomorrow_fav_0',messages.show_rain_forecast),
            ('rain_today_fav_0',messages.show_rain_forecast),
            ('alerts_fav_0',messages.show_weather_alerts),
            ('hourly_page_1_fav_0',messages.show_hourly_forecast),
        ]
        for action, handler in paths:
            calls.clear()
            u=FakeUpdate(action)
            with patch.object(storage,'get_user_lang',lang), patch.object(storage,'get_user_region',none),\
                 patch.object(storage,'get_user_level',lang),\
                 patch.object(sys.modules[handler.__module__],handler.__name__,stub):
                await callbacks.button_callback(u,c)
            self.assertEqual(len(calls),1,action)
            if action.startswith(('day_forecast','week_summary','rain_','alerts_','hourly_page','week_forecast')):
                self.assertEqual(calls[0][0][2],'Moscow',action)
        self.assertEqual(c.user_data['fav_map']['fav_0'],'Moscow')

    async def test_wait_notice_cleanup_on_error(self):
        u=FakeUpdate('hourly_Moscow')
        async def failing():
            raise ValueError('synthetic error')
        with self.assertRaises(ValueError):
            await callbacks._pending(u.callback_query,'rus',failing())
        self.assertTrue(u.callback_query.message.sent[0].deleted)

    async def test_user_lock_blocks_duplicate_click(self):
        from handlers import interaction
        c=FakeContext(); u1=FakeUpdate('rain_Moscow'); u2=FakeUpdate('rain_Moscow')
        enter=asyncio.Event(); release=asyncio.Event(); count=[]
        async def slow(*args):
            count.append(1); enter.set(); await release.wait()
        with patch.object(interaction.callbacks,'button_callback',slow):
            one=asyncio.create_task(interaction.button_callback(u1,c))
            await enter.wait()
            await interaction.button_callback(u2,c)
            release.set(); await one
        self.assertEqual(len(count),1)
        self.assertTrue(u2.callback_query.answer_count >= 1)

    async def test_callback_city_hash_for_compare(self):
        city='ОченьДлинныйГород'*12
        payload=utils.city_callback('hourly_cmp_',city)[len('hourly_'):]
        source=await callbacks._source(payload,FakeContext(),FakeQuery(),123)
        self.assertEqual(source,(city,False,None,True))

    async def test_real_forecast_menu_rendering_with_stubbed_api(self):
        """Проходим по экрану недели, дня, часов, осадков и штормов без сети."""
        user_settings={'temperature':'fahrenheit','pressure':'hpa','wind_speed':'kmh',
                       'time_format':'12h','show_clouds':False,'show_wind_direction':False,
                       'show_wind_gust':False,'show_sunrise_sunset':False}
        async def lang(*args):return 'rus'
        async def values(*args):return user_settings
        async def level(*args):return 'adv'
        def fake_coords(city):return (55.75,37.61)
        offset=timedelta(hours=3)
        tz=timezone(offset)
        now=datetime.now(tz).replace(minute=0,second=0,microsecond=0)
        hours=[]
        for i in range(48):
            hours.append({'datetime':now+timedelta(hours=i),'time':'00:00','temp':10,
                'desc':'Ясно','rain':1.0 if i in (2,3,24) else 0.0,'snow':0,
                'pop':15})
        days=[]
        for i in range(8):
            date=now+timedelta(days=i)
            days.append({'date':date.strftime('%d.%m'),'date_full':date.strftime('%d.%m'),
                'day_short':'Пн','day_full':'Понедельник','local_date':date.date(),
                'timezone_offset':10800,'timezone_name':None,'temp_day':12,
                'temp_min':3,'temp_max':14,'feels_like':10,'desc':'Ясно',
                'pressure':1010,'humidity':70,'wind_speed':5,'sunrise':date.timestamp(),
                'sunset':date.timestamp()+40000,'wind_deg':0,'wind_gust':6,'clouds':0})
        with patch.object(storage,'get_user_lang',lang),patch.object(storage,'get_user_settings',values),\
             patch.object(storage,'get_user_level',level),patch.object(messages,'get_coordinates',fake_coords),\
             patch.object(messages,'get_hourly_forecast',lambda *args:hours),\
             patch.object(messages,'get_daily_forecast',lambda *args:days),\
             patch.object(messages,'get_weather_alerts',lambda *args: []):
            for f, args in [
                 (messages.show_hourly_forecast,(0,True,'fav_0')),
                 (messages.show_rain_forecast,(1,True,'fav_0')),
                 (messages.show_week_forecast,(True,'fav_0')),
                 (messages.show_day_forecast,(1,True,'fav_0')),
                 (messages.show_week_summary,(True,'fav_0')),
                 (messages.show_week_summary_tomorrow,(True,'fav_0')),
                 (messages.show_weather_alerts,(True,'fav_0'))]:
                u=FakeUpdate('weather_fav_fav_0');c=FakeContext()
                await f(u,c,'Moscow',*args)
                self.assertTrue(u.callback_query.edits, f.__name__)
                body, markup=u.callback_query.edits[-1]
                self.assertTrue(body)
                self.assertTrue(markup)
                self.assertTrue(all(len(button.callback_data.encode())<=64
                    for row in markup.inline_keyboard for button in row),f.__name__)
                if f==messages.show_day_forecast:
                    self.assertIn('°F',body)
                    self.assertNotIn('Облачность',body)
                if f==messages.show_weather_alerts:
                    self.assertIn('предупреждений',body.lower())

if __name__=='__main__':unittest.main()
