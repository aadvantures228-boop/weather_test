"""Проверки Pre-release 1.1-2 без интернета, Telegram API и PostgreSQL."""
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_pre_release import FakeContext, FakeUpdate, FakeQuery
import favorites
import weather_api
from weather_format import current_text
from config.defaults import DEFAULT_SETTINGS
from config.texts import changelog, ui, VERSION
from handlers import admin, messages, callbacks, navigation
from handlers.features import compare
import storage
import utils


class StubDB:
    def __init__(self, favorites=None):
        self.favorites = favorites if favorites is not None else []
        self.updates = []
        self.users = {456: {'user_id': 456}}
    async def get_user_favorites(self, user_id):
        return list(self.favorites)
    async def update_user_field(self, user_id, field, value):
        self.updates.append((user_id,field,value))
        if field == 'favorites':
            self.favorites = value
    async def get_user(self, user_id):
        return self.users.get(user_id)


def resolved(city):
    names = {'Москва': ('RU:55.7500:37.6100','Москва','Moscow'),
             'Moscow': ('RU:55.7500:37.6100','Москва','Moscow'),
             'London': ('GB:51.5100:-0.1300','Лондон','London'),
             'Лондон': ('GB:51.5100:-0.1300','Лондон','London')}
    if city not in names:
        return None
    identity, ru, en = names[city]
    return {'id': identity, 'name': city,
            'lat': 55.75 if city in ('Москва','Moscow') else 51.51,
            'lon': 37.61 if city in ('Москва','Moscow') else -.13,
            'country': identity[:2], 'names': {'rus': ru, 'eng': en}}


class CityValidationTests(unittest.TestCase):
    def test_rejects_67_and_markup(self):
        for bad in ('67','12345','','<b>Paris</b>','https://test.com','123','🌤️'):
            self.assertFalse(weather_api.valid_city_input(bad),bad)
    def test_allows_real_city_names_and_mixed_digits(self):
        for good in ('Москва', 'Moscow', 'Санкт-Петербург', "St. John's", 'Route 66', 'Moscow, Idaho, US'):
            self.assertTrue(weather_api.valid_city_input(good),good)
    def test_identity_uses_geo_not_spelling(self):
        with patch('weather_api.get_city_identity',side_effect=resolved):
            self.assertTrue(weather_api.same_city('Москва','Moscow'))
            self.assertFalse(weather_api.same_city('Москва','London'))


class FavoritesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        favorites._locks.clear()
        self.geo = patch('favorites.get_city_identity',side_effect=resolved)
        self.geo.start()
    async def asyncTearDown(self):
        self.geo.stop()
    async def test_migrates_and_deduplicates_old_strings(self):
        db = StubDB(['Москва','Moscow','London','Неизвестный посёлок'])
        names = await favorites.list_names(db,314,'rus')
        self.assertEqual(names,['Москва','Лондон','Неизвестный посёлок'])
        self.assertEqual(len(db.favorites),3)
        self.assertEqual(db.favorites[-1],'Неизвестный посёлок')
        self.assertTrue(await favorites.contains(db,314,'Moscow'))
    async def test_cross_language_add_and_remove(self):
        db = StubDB()
        self.assertTrue(await favorites.add(db,315,'Москва'))
        self.assertFalse(await favorites.add(db,315,'Moscow'))
        self.assertEqual(await favorites.list_names(db,315,'eng'),['Moscow'])
        self.assertTrue(await favorites.remove(db,315,'Moscow'))
        self.assertEqual(await favorites.list_names(db,315,'rus'),[])
    async def test_favorites_limit_preserved(self):
        db=StubDB([f'City{i}' for i in range(15)])
        self.assertFalse(await favorites.add(db,316,'Москва'))
        self.assertEqual(len(db.favorites),15)
    async def test_legacy_unnamed_city_survives_api_failure(self):
        db=StubDB(['Неизвестный посёлок'])
        self.assertEqual(await favorites.list_names(db,317),['Неизвестный посёлок'])
        self.assertEqual(db.favorites,['Неизвестный посёлок'])


class WeatherDisplayTests(unittest.TestCase):
    def setUp(self):
        self.raw={'main':{'temp':24,'feels_like':24,'humidity':60,'pressure':1013,
                          'sea_level':1015,'grnd_level':1007},
                  'weather':[{'id':800,'description':'clear sky'}],
                  'visibility':7400, 'wind':{'speed':3}, 'sys':{}, 'clouds':{}}
    def test_pressure_is_always_visible_others_default_off(self):
        text=current_text('Москва',self.raw,'rus',{})
        self.assertIn('Давление: ',text)
        self.assertNotIn('Точка росы',text)
        self.assertNotIn('Дальность видимости',text)
        self.assertNotIn('Давление на уровне моря',text)
        self.assertFalse(DEFAULT_SETTINGS['show_dew_point'])
        self.assertFalse(DEFAULT_SETTINGS['show_visibility'])
        self.assertFalse(DEFAULT_SETTINGS['show_pressure_sea'])
        self.assertNotIn('show_pressure_ground', DEFAULT_SETTINGS)
    def test_optional_measurements_visible_if_enabled(self):
        text=current_text('Москва',self.raw,'rus',{'show_dew_point':True,'show_visibility':True,
           'show_pressure_sea':True})
        for term in ('Точка росы','Дальность видимости: 7.4 км',
                     'Давление на уровне моря',
                     'Давление: '):
            self.assertIn(term,text)
        self.assertNotIn('Осадки за последний час',text)
        self.assertNotIn('Мин. температура',text)


class InterfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_version_news_and_changelog_no_secret(self):
        self.assertEqual(VERSION,'Release 1.1')
        for lang in ('rus','eng'):
            self.assertIn('Release 1.1',ui('start',lang))
            self.assertNotIn('шторм',changelog('pre_1_1_1',lang).lower())
            self.assertNotIn('storm',changelog('pre_1_1_1',lang).lower())
            self.assertIn('1.1-2',changelog('pre_1_1_2',lang))
    async def test_both_pre_releases_on_same_row(self):
        update=FakeUpdate(data='updates_menu');context=FakeContext()
        with patch('handlers.messages.storage.get_user_lang',AsyncMock(return_value='rus')):
            await messages.show_updates_menu(update,context)
        rows=update.callback_query.edits[-1][1].inline_keyboard
        self.assertTrue(any([b.callback_data for b in row] == ['changelog_1_1','changelog_release_1_1'] for row in rows))
    async def test_coordinates_are_code_only(self):
        update=FakeUpdate(data='extra_Москва'); context=FakeContext()
        info={'lat':55.75575,'lon':37.6173,'timezone':10800}
        async def get_city(*args):return 'rus'
        with patch('handlers.callbacks.storage.get_user_lang',AsyncMock(return_value='rus')),\
             patch('handlers.callbacks.storage.get_user_region',AsyncMock(return_value=None)),\
             patch('handlers.callbacks.storage.get_user_settings',AsyncMock(return_value={})),\
             patch('handlers.callbacks.get_weather_data',return_value=(info,'text')),\
             patch('handlers.callbacks.get_city_details',return_value={'country':'Россия','state':'Московская область'}),\
             patch('handlers.callbacks._edit',new_callable=AsyncMock) as edit:
            await callbacks.button_callback(update,context)
        text=edit.await_args.args[2]
        self.assertIn('<code>55.75575, 37.61730</code>',text)
        self.assertNotIn('<code>Координаты:',text)
        self.assertEqual(edit.await_args.kwargs['parse_mode'],'HTML')
    async def test_admin_buttons_and_page_identity(self):
        buttons=utils.create_user_detail_keyboard(456,'rus')
        codes=[b.callback_data for r in buttons.inline_keyboard for b in r]
        for code in ('admin_direct_message_456','admin_promote_456','admin_demote_456','admin_users_list'):
            self.assertIn(code,codes)
        self.assertEqual(navigation._page_id('admin_demote_456'),'admin_user_detail')
    async def test_promote_requires_valid_key_and_sets_level(self):
        c=FakeContext(); c.bot_data['db']=StubDB()
        u=FakeUpdate(text='bad'); c.user_data.update(admin_action='promote',admin_action_target=456)
        with patch.object(admin,'ADMIN_ID',123),\
             patch('handlers.admin.storage.validate_activation_key',return_value=None),\
             patch('handlers.admin.storage.get_user_lang',AsyncMock(return_value='rus')):
            self.assertTrue(await admin.handle_direct_input(u,c,'bad','rus'))
        self.assertEqual(c.user_data['admin_action'],'promote')
        c.bot.send_message=AsyncMock()
        with patch.object(admin,'ADMIN_ID',123),\
             patch('handlers.admin.storage.validate_activation_key',return_value='adv'),\
             patch('handlers.admin.storage.set_user_level',new_callable=AsyncMock) as set_level,\
             patch('handlers.admin.storage.get_user_lang',AsyncMock(return_value='rus')):
            self.assertTrue(await admin.handle_direct_input(u,c,'KEY','rus'))
        set_level.assert_awaited_once_with(c,456,'adv')
        self.assertNotIn('admin_action',c.user_data)
        c.bot.send_message.assert_awaited_once()
    async def test_demote_is_basic_and_no_key(self):
        c=FakeContext();c.bot_data['db']=StubDB();c.bot.send_message=AsyncMock()
        u=FakeUpdate(data='admin_demote_456')
        with patch.object(admin,'ADMIN_ID',123),\
             patch('handlers.admin.storage.get_user_lang',AsyncMock(return_value='rus')),\
             patch('handlers.admin.storage.set_user_level',new_callable=AsyncMock) as set_level,\
             patch('handlers.admin._render_user_detail',new_callable=AsyncMock) as render:
            await admin.demote_user(u,c)
        set_level.assert_awaited_once_with(c,456,'free')
        render.assert_awaited_once()
    async def test_non_admin_cannot_send_or_promote(self):
        c=FakeContext();c.bot_data['db']=StubDB()
        c.user_data.update(admin_action='promote',admin_action_target=456)
        u=FakeUpdate(text='ABC')
        with patch.object(admin,'ADMIN_ID',999):
            self.assertFalse(await admin.handle_direct_input(u,c,'ABC','rus'))
            q=FakeQuery('admin_promote_456')
            self.assertIsNone(await admin._get_target(q,c,'admin_promote_'))
    async def test_admin_direct_message_without_id_input(self):
        c=FakeContext();u=FakeUpdate(data='admin_direct_message_456')
        with patch.object(admin,'ADMIN_ID',123),\
             patch('handlers.admin._get_target',AsyncMock(return_value=456)),\
             patch('handlers.admin.storage.get_user_lang',AsyncMock(return_value='rus')):
            await admin.start_user_action(u,c,'message')
        self.assertEqual(c.user_data['admin_action_target'],456)
        self.assertEqual(c.user_data['admin_action'],'message')
