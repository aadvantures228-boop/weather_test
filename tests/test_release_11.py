"""Release 1.1: офлайн-регрессии новых функций и совместимости."""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_pre_release import FakeUpdate, FakeQuery, FakeContext
import favorites as favorite_compares
import weather_api
from weather_format import build_intervals, render_intervals
from handlers import messages, callbacks, navigation, admin
from handlers.features.compare import compare_cities
from config.defaults import DEFAULT_SETTINGS
from config.texts import changelog, VERSION, ui
import storage
import utils


class DB:
    def __init__(self):
        self.pairs = []
        self.updates = []
    async def get_user_comparisons(self, user_id):
        return list(self.pairs)
    async def update_user_field(self, user_id, field, value):
        self.updates.append((user_id, field, value))
        if field == 'favorite_compares':
            self.pairs = value


def resolve(name):
    records = {'Москва': ('RU:55:37', 'Москва', 'Moscow', 55, 37),
               'Moscow': ('RU:55:37', 'Москва', 'Moscow', 55, 37),
               'Лондон': ('GB:51:0', 'Лондон', 'London', 51, 0),
               'London': ('GB:51:0', 'Лондон', 'London', 51, 0),
               'Berlin': ('DE:52:13', 'Берлин', 'Berlin', 52, 13)}
    if name not in records:
        return None
    id_, ru, en, lat, lon = records[name]
    return {'id':id_, 'name':name, 'country':id_[:2], 'lat':lat, 'lon':lon,
            'names':{'rus':ru,'eng':en}}


class SavedComparisons(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DB()
        self.patch = patch.object(favorite_compares, 'get_city_identity', side_effect=resolve)
        self.patch.start()
        self.addAsyncCleanup(self._stop)
    async def _stop(self):
        self.patch.stop()
    async def test_save_localized_pairs_and_reject_reversed_duplicate(self):
        self.assertTrue(await favorite_compares.compare_add(self.db, 1, 'Москва', 'London'))
        self.assertFalse(await favorite_compares.compare_add(self.db, 1, 'Лондон', 'Moscow'))
        self.assertEqual(len(self.db.pairs),1)
        self.assertEqual((await favorite_compares.compare_list_pairs(self.db,1,'rus'))[0]['first'], 'Москва')
        self.assertEqual((await favorite_compares.compare_list_pairs(self.db,1,'eng'))[0]['second'], 'London')
        self.assertEqual((await favorite_compares.compare_list_pairs(self.db,1,'eng'))[0]['first_coords'], (55, 37))
    async def test_remove_and_clear_only_compares(self):
        await favorite_compares.compare_add(self.db, 1, 'Москва','Berlin')
        self.assertFalse(await favorite_compares.compare_remove(self.db,1,19))
        self.assertTrue(await favorite_compares.compare_remove(self.db,1,0))
        self.assertEqual(self.db.pairs,[])
        await favorite_compares.compare_add(self.db,1,'Moscow','London')
        await favorite_compares.compare_clear(self.db,1)
        self.assertEqual(self.db.pairs,[])
        self.assertTrue(all(field == 'favorite_compares' for _,field,_ in self.db.updates))
    async def test_favorites_render_cities_then_pairs_without_header(self):
        up = FakeUpdate(text='Избранное'); ctx=FakeContext()
        pairs=[{'index':0,'first':'Москва','second':'Лондон'}]
        with patch('handlers.messages.storage.get_user_lang', AsyncMock(return_value='rus')), \
             patch('handlers.messages.storage.get_user_favorites', AsyncMock(return_value=['Москва'])), \
             patch('handlers.messages.storage.get_user_comparisons',AsyncMock(return_value=pairs)), \
             patch('handlers.messages.storage.get_user_settings',AsyncMock(return_value={})), \
             patch('handlers.messages.get_weather_data',return_value=({'temp':10},'')):
            await messages.favorites(up,ctx)
        buttons=up.message.sent[-1].reply_markup.inline_keyboard
        self.assertTrue(buttons[0][0].text.startswith('🏙️'))
        self.assertTrue(buttons[1][0].text.startswith('⚖️'))
        self.assertNotIn('Избранные сравнения',up.message.sent[-1].text)
    async def test_saved_compare_keyboard_only_back(self):
        markup=utils.create_compare_result_keyboard('Москва','Лондон','rus',favorite_view=True)
        self.assertEqual(len(markup.inline_keyboard),1)
        self.assertEqual(markup.inline_keyboard[0][0].callback_data,'favorites')
        self.assertNotIn('Начать',markup.inline_keyboard[0][0].text)


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.start=datetime(2026,11,16,5,0,tzinfo=timezone.utc)
        self.items=[]
    def h(self,offset,rain=0,snow=0,weather_id=800):
        return {'datetime':self.start+timedelta(hours=offset),
                'rain':rain,'snow':snow,'weather_id':weather_id,'step_hours':1,
                'desc':'ясно'}
    def test_overlapping_rain_snow_own_ranges_and_sums(self):
        rows=[self.h(0,20),self.h(1,15,50),self.h(2,15)]
        groups=build_intervals(rows,self.start.date())
        self.assertEqual(len(groups),2)
        rain,snow=groups
        self.assertEqual((rain['kind'],rain['start'].hour,rain['end'].hour,rain['amount']),('rain',5,8,50))
        self.assertEqual((snow['kind'],snow['start'].hour,snow['end'].hour,snow['amount']),('snow',6,7,50))
        rendered=render_intervals(groups)
        self.assertIn('05:00–08:00 — 50.0 мм',rendered)
        self.assertIn('06:00–07:00 — 50.0 мм',rendered)
    def test_thunder_without_rain_and_separate_intervals(self):
        groups=build_intervals([self.h(0,rain=2),self.h(2,weather_id=201),self.h(4,rain=3)],self.start.date())
        self.assertEqual([g['kind'] for g in groups], ['rain','thunder','rain'])
        self.assertEqual(len(groups),3)
        self.assertIn('Гроза',render_intervals(groups))
    def test_three_hour_forecast_end_time_and_midnight(self):
        day=datetime(2026,11,16,0,0,tzinfo=timezone.utc)
        rows=[{'datetime':day+timedelta(hours=1),'rain':12,'snow':0,'weather_id':500,'step_hours':3}]
        groups=build_intervals(rows,day.date())
        self.assertEqual(len(groups),1)
        self.assertAlmostEqual(groups[0]['amount'],4.0)
        self.assertEqual(groups[0]['start'].hour,0)
        self.assertEqual(groups[0]['end'].hour,1)


class ReleaseLogic(unittest.TestCase):
    def test_refresh_disabled_default_and_enabled(self):
        self.assertIs(DEFAULT_SETTINGS['show_refresh_btn'],False)
        kb=utils.create_weather_keyboard('Moscow',False,None,settings={})
        self.assertFalse(any('refresh_weather_' in b.callback_data for row in kb.inline_keyboard for b in row))
        kb=utils.create_weather_keyboard('Moscow',False,None,settings={'show_refresh_btn':True})
        self.assertTrue(any('refresh_weather_' in b.callback_data for row in kb.inline_keyboard for b in row))
        kb=utils.create_compare_result_keyboard('Moscow','London','rus',settings={'show_refresh_btn':True})
        self.assertTrue(any(b.callback_data=='refresh_compare' for row in kb.inline_keyboard for b in row))
    def test_region_button_uses_geographical_match(self):
        kb=utils.create_weather_keyboard('Moscow',False,'Москва',is_current_region=True)
        self.assertNotIn('set_region_',str([[b.callback_data for b in row] for row in kb.inline_keyboard]))
    def test_release_version_and_history_not_hidden_from_users(self):
        self.assertEqual(VERSION,'Release 1.1')
        self.assertIn('Release 1.1',ui('start'))
        for lang in ('rus','eng'):
            self.assertIn('1.1',changelog('release_1_1',lang))
            self.assertNotIn('шторм',changelog('pre_1_1_1',lang).lower())
            self.assertNotIn('storm',changelog('pre_1_1_1',lang).lower())
    def test_new_changelog_parent_child_pages(self):
        self.assertNotEqual(navigation._page_id('changelog_release_1_1'), navigation._page_id('changelog_pre_1_1_2'))
    def test_one_paid_page_then_free_data_no_overlap(self):
        # Часовые данные включают первые 20 часов; трёхчасовой интервал,
        # пересекающийся с ними, обрезается и корректирует объём.
        now=datetime(2026,11,16,0,0,tzinfo=timezone.utc)
        paid=[{'datetime': now+timedelta(hours=i),'rain':0,'snow':0,'step_hours':1} for i in range(20)]
        free=[{'datetime':now+timedelta(hours=21), 'rain':3.0,'snow':0.,'step_hours':3},
              {'datetime':now+timedelta(hours=24),'rain':6.,'snow':0.,'step_hours':3}]
        with patch('weather_api.get_hourly_forecast',return_value=paid), patch('weather_api.get_three_hour_forecast',return_value=free):
            result=weather_api.get_extended_hourly_forecast(55,37,0,'rus')
        self.assertEqual(len(result),22)
        self.assertAlmostEqual(result[20]['rain'],1.)
        self.assertEqual(result[20]['interval_start'], now+timedelta(hours=20))
        self.assertEqual(result[-1]['rain'],6.)


class ReleaseIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_changelog_menu_release_and_pre(self):
        up=FakeUpdate(data='updates_menu');ctx=FakeContext()
        with patch('handlers.messages.storage.get_user_lang', AsyncMock(return_value='rus')):
            await messages.show_updates_menu(up,ctx)
            rows=up.callback_query.message.reply_markup.inline_keyboard
            self.assertEqual([x.callback_data for x in rows[-1]], ['changelog_1_1','changelog_release_1_1'])
            up.callback_query.data='changelog_release_1_1'
            await messages.show_changelog(up,ctx,'release_1_1')
            rows=up.callback_query.message.reply_markup.inline_keyboard
            self.assertEqual([x.callback_data for x in rows[-2]], ['changelog_pre_1_1_1','changelog_pre_1_1_2'])
            up.callback_query.data='changelog_pre_1_1_1'
            await messages.show_changelog(up,ctx,'pre_1_1_1')
            self.assertEqual(len(ctx.user_data['_navigation'][navigation._key(up.callback_query)]['history']),2)
            await navigation.back(up.callback_query,ctx)
            self.assertIn('Release 1.1',up.callback_query.message.text)
    async def test_saving_comparison_uses_correct_chat_message(self):
        up=FakeUpdate(data='compare_save');ctx=FakeContext()
        msg_id=up.callback_query.message.message_id
        ctx.user_data['compare_by_message']={msg_id:['Москва','Лондон']}
        with patch('handlers.callbacks.storage.get_user_lang',AsyncMock(return_value='rus')), \
             patch('handlers.callbacks.storage.get_user_region',AsyncMock(return_value=None)), \
             patch('handlers.callbacks.storage.get_user_settings',AsyncMock(return_value={'show_refresh_btn':True})), \
             patch('handlers.callbacks.storage.add_user_comparison',AsyncMock(return_value=True)) as add:
            await callbacks.button_callback(up,ctx)
        add.assert_awaited_once_with(ctx,123,'Москва','Лондон')
        rows=up.callback_query.message.reply_markup.inline_keyboard
        self.assertTrue(any(b.callback_data=='compare_remove_saved' for row in rows for b in row))
        self.assertTrue(any(b.callback_data=='refresh_compare' for row in rows for b in row))

    async def test_refresh_weather_is_rate_limited_and_free(self):
        up=FakeUpdate(data='refresh_weather_Москва');ctx=FakeContext()
        mocked_weather=({'city':'Москва','temp':10},'Погода в Москве')
        with patch('handlers.callbacks.storage.get_user_lang',AsyncMock(return_value='rus')), \
             patch('handlers.callbacks.storage.get_user_region',AsyncMock(return_value=None)), \
             patch('handlers.callbacks.storage.get_user_settings',AsyncMock(return_value={'show_refresh_btn':True})), \
             patch('handlers.callbacks.storage.get_api_units',AsyncMock(return_value='metric')), \
             patch('handlers.callbacks.storage.is_city_in_favorites',AsyncMock(return_value=False)), \
             patch('handlers.callbacks.get_weather_data',return_value=mocked_weather) as get_weather:
            await callbacks.button_callback(up,ctx)
            await callbacks.button_callback(up,ctx)
        self.assertEqual(get_weather.call_count,1)
        self.assertTrue(get_weather.call_args.args[-1])  # force_refresh=True только для бесплатной погоды

    async def test_saved_compare_callback_displays_only_return(self):
        up=FakeUpdate(data='favorite_compare_0');ctx=FakeContext()
        pair={'index':0,'first':'Москва','second':'Лондон',
              'first_coords':(55.0,37.0),'second_coords':(51.0,0.0)}
        with patch('handlers.callbacks.storage.get_user_lang',AsyncMock(return_value='rus')), \
             patch('handlers.callbacks.storage.get_user_region',AsyncMock(return_value=None)), \
             patch('handlers.callbacks.storage.get_user_comparisons',AsyncMock(return_value=[pair])), \
             patch('handlers.callbacks.storage.get_user_settings',AsyncMock(return_value={})), \
             patch('handlers.callbacks.compare_cities',return_value=('Москва vs Лондон',None)) as compare:
            await callbacks.button_callback(up,ctx)
        compare.assert_called_once()
        self.assertEqual(compare.call_args.args[-2:], ((55.0,37.0),(51.0,0.0)))
        rows=up.callback_query.message.reply_markup.inline_keyboard
        self.assertEqual(len(rows),1)
        self.assertIn('избранному',rows[0][0].text)

    async def test_clear_favorites_no_button(self):
        up=FakeUpdate(data='confirm_clear_favorites');ctx=FakeContext()
        with patch('handlers.callbacks.storage.get_user_lang',AsyncMock(return_value='rus')), \
             patch('handlers.callbacks.storage.get_user_region',AsyncMock(return_value=None)), \
             patch('handlers.callbacks.storage.clear_user_favorites',AsyncMock()) as city_clear, \
             patch('handlers.callbacks.storage.clear_user_comparisons',AsyncMock()) as pair_clear:
            await callbacks.button_callback(up,ctx)
        self.assertEqual(up.callback_query.message.reply_markup.inline_keyboard,[])
        self.assertIn('очищен',up.callback_query.message.text)
        city_clear.assert_awaited_once()
        pair_clear.assert_awaited_once()
    async def test_admin_verification_only_clears_confirmed_bad_regions(self):
        up=FakeUpdate(data='admin_check_users_confirm');ctx=FakeContext()
        up.callback_query.from_user.id=999
        rows={1:{'region':'67'},2:{'region':'Москва'},3:{'region':'City with timeout'}}
        class FakeDB:
            def __init__(self):self.resets=[]
            async def get_user_region(self,uid):return rows[uid]['region']
            async def update_user_field(self,uid,field,val):self.resets.append((uid,field,val))
        db=FakeDB()
        with patch('handlers.admin.ADMIN_ID',999), patch('handlers.admin.storage.get_user_lang',AsyncMock(return_value='rus')), \
             patch('handlers.admin.storage.get_db',return_value=db), patch('handlers.admin.storage.get_all_users',AsyncMock(return_value=rows)), \
             patch('weather_api.region_is_valid',side_effect=lambda city: False if city=='67' else True if city=='Москва' else None), \
             patch('asyncio.sleep',new_callable=AsyncMock):
            await admin.check_all_regions(up,ctx)
        self.assertEqual(db.resets,[(1,'region',None)])
        self.assertIn('Сброшено неверных: 1',up.callback_query.message.text)
        self.assertIn('Не удалось проверить: 1',up.callback_query.message.text)


if __name__ == '__main__':
    unittest.main()
