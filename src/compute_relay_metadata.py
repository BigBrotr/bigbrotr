from aiohttp import ClientSession, ClientTimeout, WSMsgType
from aiohttp_socks import ProxyConnector
import json
import uuid
import asyncio
from relay_metadata import RelayMetadata
from relay import Relay
from utils import generate_event, generate_nostr_keypair
import time


async def fetch_nip11_metadata(relay_id, session, timeout):
    headers = {'Accept': 'application/nostr+json'}
    for schema in ['https://', 'http://']:
        try:
            async with session.get(schema + relay_id, headers=headers, timeout=timeout) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    pass
        except Exception as e:
            pass
    return None


def parse_nip11_response(nip11_response):
    if nip11_response is None:
        return {'nip11_success': False}
    return {
        'nip11_success': True,
        'name': nip11_response.get('name'),
        'description': nip11_response.get('description'),
        'banner': nip11_response.get('banner'),
        'icon': nip11_response.get('icon'),
        'pubkey': nip11_response.get('pubkey'),
        'contact': nip11_response.get('contact'),
        'supports_nips': nip11_response.get('supported_nips'),
        'software': nip11_response.get('software'),
        'version': nip11_response.get('version'),
        'privacy_policy': nip11_response.get('privacy_policy'),
        'terms_of_service': nip11_response.get('terms_of_service'),
        'limitation': nip11_response.get('limitation'),
        'extra_fields': {
            key: value for key, value in nip11_response.items() if key not in [
                'name', 'description', 'banner', 'icon', 'pubkey', 'contact',
                'supported_nips', 'software', 'version', 'privacy_policy',
                'terms_of_service', 'limitation'
            ]
        }
    }


async def check_connectivity(session, relay_url, timeout):
    rtt_open = None
    try:
        time_start = time.time()
        async with session.ws_connect(relay_url, timeout=timeout) as ws:
            time_end = time.time()
            rtt_open = int((time_end - time_start) * 1000)
    except Exception as e:
        pass
    return rtt_open


async def check_readability(session, relay_url, timeout):
    rtt_read = None
    readable = False
    try:
        async with session.ws_connect(relay_url, timeout=timeout) as ws:
            subscription_id = uuid.uuid4().hex
            request = ["REQ", subscription_id, {"limit": 1}]
            time_start = time.time()
            await ws.send_str(json.dumps(request))
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if msg.type == WSMsgType.TEXT:
                    if rtt_read is None:
                        time_end = time.time()
                        rtt_read = int((time_end - time_start) * 1000)
                    data = json.loads(msg.data)
                    if data[0] in ["EVENT", "EOSE"] and data[1] == subscription_id:
                        readable = True
                        break
                    else:
                        break
                else:
                    break
    except Exception as e:
        pass
    return rtt_read, readable


async def check_writability(session, relay_url, timeout, sec, pub, target_difficulty):
    rtt_write = None
    writable = False
    try:
        async with session.ws_connect(relay_url, timeout=timeout) as ws:
            event = generate_event(
                sec,
                pub,
                30166,
                [["d", relay_url]],
                "{}",
                target_difficulty=target_difficulty,
                timeout=20
            )
            request = ["EVENT", event]
            time_start = time.time()
            await ws.send_str(json.dumps(request))
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                if msg.type == WSMsgType.TEXT:
                    if rtt_write is None:
                        time_end = time.time()
                        rtt_write = int((time_end - time_start) * 1000)
                    data = json.loads(msg.data)
                    if data[0] == "OK" and data[1] == event["id"] and data[2] == True:
                        writable = True
                        break
                    else:
                        break
                else:
                    break
    except Exception as e:
        print(f"Error: {e}")
        pass
    return rtt_write, writable


async def fetch_connection_metadata(relay_id, session, timeout, sec, pub, target_difficulty):
    rtt_open = None
    rtt_read = None
    rtt_write = None
    writable = False
    readable = False
    for schema in ['wss://', 'ws://']:
        relay_url = schema + relay_id
        rtt_open = await check_connectivity(session, relay_url, timeout)
        if rtt_open is not None:
            rtt_read, readable = await check_readability(session, relay_url, timeout)
            rtt_write, writable = await check_writability(session, relay_url, timeout, sec, pub, target_difficulty)
            if readable or writable:
                return {
                    'rtt_open': rtt_open,
                    'rtt_read': rtt_read,
                    'rtt_write': rtt_write,
                    'writable': writable,
                    'readable': readable
                }
    return None


def parse_connection_response(connection_response):
    if connection_response is None:
        return {'connection_success': False}
    return {
        'connection_success': True,
        'rtt_open': connection_response.get('rtt_open'),
        'rtt_read': connection_response.get('rtt_read'),
        'rtt_write': connection_response.get('rtt_write'),
        'writable': connection_response.get('writable'),
        'readable': connection_response.get('readable')
    }


async def compute_relay_metadata(relay, sec, pub, socks5_proxy_url=None, timeout=10):
    relay_id = relay.url.removeprefix('wss://')
    connector = ProxyConnector.from_url(
        socks5_proxy_url) if relay.network == 'tor' else None
    async with ClientSession(connector=connector, timeout=ClientTimeout(total=timeout)) as session:
        nip11_raw = await fetch_nip11_metadata(relay_id, session, timeout)
        nip11_response = parse_nip11_response(nip11_raw)
    target_difficulty = nip11_response.get(
        'limitation', {}).get('min_pow_difficulty', None)
    target_difficulty = target_difficulty if isinstance(
        target_difficulty, int) else None
    connector = ProxyConnector.from_url(
        socks5_proxy_url) if relay.network == 'tor' else None
    async with ClientSession(connector=connector, timeout=ClientTimeout(total=timeout)) as session:
        connection_raw = await fetch_connection_metadata(relay_id, session, timeout, sec, pub, target_difficulty)
        connection_response = parse_connection_response(connection_raw)
    metadata = {
        'relay': relay,
        'generated_at': int(time.time()),
        **nip11_response,
        **connection_response
    }
    return RelayMetadata.from_dict(metadata)

sec, pub = generate_nostr_keypair()
socks5_proxy_url = "socks5://127.0.0.1:9050"
relay = Relay(url="wss://relay.damus.io")
print(asyncio.run(compute_relay_metadata(relay, sec, pub, socks5_proxy_url)))
