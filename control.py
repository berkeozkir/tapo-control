"""Local Tapo bulb discovery and control. Credentials stay in process memory."""
import argparse
import asyncio
import getpass
import json
import os
import sys

from kasa import Discover, Module
from kasa.exceptions import AuthenticationError, KasaException, UnsupportedDeviceError


def bounded(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"Must be between {low} and {high}")
        return number
    return parse


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='192.168.1.110')
    parser.add_argument('--target', default='192.168.1.255', help='Discovery broadcast address')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('discover', 'status', 'on', 'off', 'interactive'):
        commands.add_parser(name)
    commands.add_parser('brightness').add_argument('value', type=bounded(1, 100))
    commands.add_parser('white').add_argument('kelvin', type=bounded(2500, 6500))
    color = commands.add_parser('color')
    color.add_argument('hue', type=bounded(0, 360))
    color.add_argument('saturation', type=bounded(0, 100))
    return parser.parse_args()


async def discover(target):
    rows = {}
    def found(raw):
        info = raw['discovery_response'].get('result', {})
        ip = raw['meta']['ip']
        rows[ip] = {
            'ip': ip, 'model': info.get('device_model', 'legacy device'),
            'encryption': info.get('mgt_encrypt_schm', {}).get('encrypt_type'),
        }
    devices = await Discover.discover(target=target, discovery_timeout=8, on_discovered_raw=found)
    try:
        print(json.dumps(list(rows.values()), indent=2))
        print(f'{len(rows)} device(s) responded; {len(devices)} supported by this library.')
    finally:
        for device in devices.values():
            await device.disconnect()


def status(device):
    result = {'ip': device.host, 'name': device.alias, 'model': device.model, 'on': device.is_on}
    light = device.modules.get(Module.Light)
    if light:
        result['brightness'] = light.brightness
        if Module.Color in device.modules:
            result['hsv'] = list(light.hsv)
        if Module.ColorTemperature in device.modules:
            result['kelvin'] = light.color_temp
    print(json.dumps(result, indent=2, ensure_ascii=False))


async def command(device, name, values):
    light = device.modules.get(Module.Light)
    if name == 'on':
        await device.turn_on()
    elif name == 'off':
        await device.turn_off()
    elif name in ('brightness', 'white', 'color'):
        if light is None:
            raise ValueError('This device has no light module')
        if name == 'brightness':
            await light.set_brightness(bounded(1, 100)(values[0]))
        elif name == 'white':
            await light.set_color_temp(bounded(2500, 6500)(values[0]))
        else:
            await light.set_hsv(bounded(0, 360)(values[0]), bounded(0, 100)(values[1]))
    elif name != 'status':
        raise ValueError('Unknown command')
    await device.update()
    status(device)


async def main(args):
    if args.command == 'discover':
        await discover(args.target)
        return
    # Discover before requesting secrets, so unsupported firmware fails immediately.
    device = await Discover.discover_single(args.host)
    if device is None:
        raise ValueError('No device responded at that address')
    await device.disconnect()
    username = os.environ.get('KASA_USERNAME') or input('Tapo account email: ').strip()
    password = os.environ.get('KASA_PASSWORD') or getpass.getpass('Tapo password (hidden): ')
    device = await Discover.discover_single(args.host, username=username, password=password)
    if device is None:
        raise ValueError('Device stopped responding')
    try:
        await device.update()
        if 'L530' not in device.model:
            raise ValueError(f'Refusing to control unexpected model {device.model}')
        if args.command == 'interactive':
            status(device)
            print('Commands: status | on | off | brightness 50 | white 2700 | color 240 100 | quit')
            while True:
                parts = input('tapo> ').split()
                if not parts:
                    continue
                if parts[0] in ('quit', 'exit'):
                    break
                expected = {'status': 0, 'on': 0, 'off': 0, 'brightness': 1, 'white': 1, 'color': 2}
                try:
                    if parts[0] not in expected or len(parts) - 1 != expected[parts[0]]:
                        raise ValueError('Invalid command or number of arguments')
                    await command(device, parts[0], parts[1:])
                except (ValueError, argparse.ArgumentTypeError) as error:
                    print(error)
        else:
            values = [args.value] if args.command == 'brightness' else [args.kelvin] if args.command == 'white' else [args.hue, args.saturation] if args.command == 'color' else []
            await command(device, args.command, values)
    finally:
        await device.disconnect()


if __name__ == '__main__':
    try:
        asyncio.run(main(arguments()))
    except UnsupportedDeviceError:
        print('Unsupported protocol. Enable Tapo app > Me > Tapo Lab > Third-Party Compatibility, then retry.', file=sys.stderr)
        sys.exit(2)
    except AuthenticationError:
        print('Authentication failed. Check your Tapo credentials and Third-Party Compatibility setting.', file=sys.stderr)
        sys.exit(3)
    except (KasaException, OSError, ValueError) as error:
        print(f'Connection/control failed ({type(error).__name__}). Check the bulb IP, power, and network.', file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print('\nStopped.')
