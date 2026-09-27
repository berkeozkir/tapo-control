"""Local discovery and control, isolated from the desktop interface."""
import asyncio
import ipaddress
import socket

import psutil
from kasa import Discover, Module
from kasa.exceptions import AuthenticationError


def broadcast_targets():
    targets = {'255.255.255.255'}
    stats = psutil.net_if_stats()
    for name, addresses in psutil.net_if_addrs().items():
        if name not in stats or not stats[name].isup:
            continue
        for address in addresses:
            if address.family == socket.AF_INET and address.netmask:
                ip = ipaddress.ip_address(address.address)
                if not ip.is_loopback and not ip.is_link_local:
                    network = ipaddress.ip_network(f'{ip}/{address.netmask}', strict=False)
                    targets.add(str(network.broadcast_address))
    return sorted(targets)


def snapshot(device):
    light = device.modules[Module.Light]
    return dict(id=device.mac or device.host, host=device.host, name=device.alias or device.model,
                model=device.model, on=device.is_on, online=True, brightness=light.brightness,
                color=Module.Color in device.modules, white=Module.ColorTemperature in device.modules,
                kelvin=light.color_temp if Module.ColorTemperature in device.modules else 0,
                hsv=list(light.hsv) if Module.Color in device.modules else [0, 0, 100])


class Backend:
    def __init__(self):
        self.devices = {}
        self.credentials = None

    async def close(self):
        for device in self.devices.values():
            await device.disconnect()
        self.devices.clear()

    async def scan(self, username, password):
        if self.credentials != (username, password):
            await self.close()
            self.credentials = (username, password)
        raw = {}
        discovered = {}
        errors = []

        def found(item):
            info = item['discovery_response'].get('result', {})
            if 'BULB' in info.get('device_type', '') or 'LIGHT' in info.get('device_type', ''):
                raw[item['meta']['ip']] = info

        async def subnet(target):
            try:
                devices = await Discover.discover(target=target, discovery_timeout=3,
                    username=username, password=password, on_discovered_raw=found)
                for host, device in devices.items():
                    if host in discovered:
                        await device.disconnect()
                    else:
                        discovered[host] = device
            except Exception as error:
                errors.append(type(error).__name__)

        await asyncio.gather(*(subnet(target) for target in broadcast_targets()))
        rows, failed = [], []
        semaphore = asyncio.Semaphore(6)

        async def inspect(host, device):
            async with semaphore:
                try:
                    # Ignore non-light devices before authenticating where possible.
                    if host not in raw and device.device_type.value not in ('bulb', 'lightstrip', 'unknown'):
                        await device.disconnect()
                        return
                    await asyncio.wait_for(device.update(), 12)
                    if Module.Light not in device.modules:
                        await device.disconnect()
                        return
                    row = snapshot(device)
                    old = self.devices.pop(row['id'], None)
                    if old:
                        await old.disconnect()
                    self.devices[row['id']] = device
                    rows.append(row)
                except AuthenticationError:
                    failed.append(f'{host}: login rejected')
                    await device.disconnect()
                except Exception:
                    failed.append(f'{host}: not responding')
                    await device.disconnect()

        await asyncio.gather(*(inspect(host, dev) for host, dev in discovered.items()))
        for host, info in raw.items():
            if host not in discovered:
                failed.append(f'{host}: enable Third-Party Compatibility in Tapo Lab')
        if not rows and not failed and errors:
            failed.append('Network discovery was blocked. Check network access and firewall settings.')
        return {'rows': rows, 'issues': failed, 'scan': True}

    async def refresh(self):
        rows = []
        for identity, device in self.devices.items():
            try:
                await asyncio.wait_for(device.update(), 6)
                rows.append(snapshot(device))
            except Exception:
                rows.append({'id': identity, 'online': False})
        return {'rows': rows, 'issues': [], 'scan': False}

    async def control(self, identity, action, value):
        device = self.devices[identity]
        light = device.modules[Module.Light]
        if action == 'power':
            await (device.turn_on() if value else device.turn_off())
        elif action == 'brightness':
            await light.set_brightness(max(1, min(100, int(value))))
        elif action == 'white':
            await light.set_color_temp(max(2500, min(6500, int(value))))
        elif action == 'color':
            await light.set_hsv(int(value[0]), int(value[1]))
        else:
            raise ValueError('Unknown control')
        await device.update()
        return {'rows': [snapshot(device)], 'issues': [], 'scan': False}
