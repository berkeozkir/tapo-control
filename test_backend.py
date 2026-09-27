import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from kasa import DeviceType, Module
from kasa.exceptions import AuthenticationError
from backend import Backend


def bulb(identity='one'):
    return SimpleNamespace(mac=identity, host='192.0.2.1', alias='Desk', model='L530E',
        is_on=True, device_type=DeviceType.Bulb,
        modules={Module.Light: SimpleNamespace(brightness=60, color_temp=2700, hsv=(0, 0, 60),
            set_brightness=AsyncMock(), set_color_temp=AsyncMock(), set_hsv=AsyncMock()),
            Module.Color: object(), Module.ColorTemperature: object()},
        update=AsyncMock(), disconnect=AsyncMock(), turn_on=AsyncMock(), turn_off=AsyncMock())


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_authenticates_lights_and_ignores_plugs(self):
        light = bulb()
        plug = bulb('plug')
        plug.device_type = DeviceType.Plug
        backend = Backend()
        with patch('backend.broadcast_targets', return_value=['192.0.2.255']), patch('backend.Discover.discover', new=AsyncMock(return_value={'a': light, 'b': plug})):
            result = await backend.scan('email', 'secret')
        self.assertEqual([row['name'] for row in result['rows']], ['Desk'])
        light.update.assert_awaited_once()
        plug.update.assert_not_awaited()
        plug.disconnect.assert_awaited_once()
        await backend.close()

    async def test_rejected_account_does_not_expose_light(self):
        light = bulb()
        light.update.side_effect = AuthenticationError('private detail')
        with patch('backend.broadcast_targets', return_value=['192.0.2.255']), patch('backend.Discover.discover', new=AsyncMock(return_value={'a': light})):
            result = await Backend().scan('email', 'wrong')
        self.assertEqual(result['rows'], [])
        self.assertIn('login rejected', result['issues'][0])
        self.assertNotIn('private detail', str(result))
        light.disconnect.assert_awaited_once()

    async def test_smart_bulb_type_unknown_until_first_update(self):
        light = bulb()
        light.device_type = DeviceType.Unknown
        with patch('backend.broadcast_targets', return_value=['192.0.2.255']), patch('backend.Discover.discover', new=AsyncMock(return_value={'a': light})):
            result = await Backend().scan('email', 'secret')
        self.assertEqual(len(result['rows']), 1)

    async def test_offline_and_recovery(self):
        backend = Backend()
        light = bulb()
        backend.devices['one'] = light
        light.update.side_effect = TimeoutError()
        self.assertFalse((await backend.refresh())['rows'][0]['online'])
        light.update.side_effect = None
        self.assertTrue((await backend.refresh())['rows'][0]['online'])
        await backend.control('one', 'brightness', 42)
        light.modules[Module.Light].set_brightness.assert_awaited_once_with(42)
        await backend.control('one', 'power', False)
        light.turn_off.assert_awaited_once()
        await backend.close()

    async def test_account_change_closes_previous_connections(self):
        backend = Backend()
        light = bulb()
        backend.devices['one'] = light
        backend.credentials = ('first', 'secret')
        with patch('backend.broadcast_targets', return_value=[]):
            await backend.scan('second', 'different')
        self.assertFalse(backend.devices)
        light.disconnect.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
