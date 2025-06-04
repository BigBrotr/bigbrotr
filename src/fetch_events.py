import uuid
import json
import asyncio
from event import Event
from relay import Relay
from aiohttp_socks import ProxyConnector
from aiohttp import ClientSession, WSMsgType, TCPConnector


async def fetch_events(relay: Relay, ids=None, authors=None, kinds=None, tags=None, since=None, until=None, limit=None, socks5_proxy_url=None, timeout=10):
    events = []
    filter = {}
    if ids:
        filter["ids"] = ids
    if authors:
        filter["authors"] = authors
    if kinds:
        filter["kinds"] = kinds
    if tags:
        for tag, values in tags.items():
            filter[f"#{tag}"] = values
    if since:
        filter["since"] = since
    if until:
        filter["until"] = until
    if limit:
        filter["limit"] = limit
    subscription_id = str(uuid.uuid4())
    request = json.dumps(["REQ", subscription_id, filter])
    if relay.network == 'tor':
        connector = ProxyConnector.from_url(socks5_proxy_url)
    else:
        connector = TCPConnector(force_close=True)
    async with ClientSession(connector=connector) as session:
        async with session.ws_connect(relay.url, timeout=timeout) as ws:
            await ws.send_str(request)
            while True:
                msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data[0] == "EVENT" and data[1] == subscription_id:
                        try:
                            event = Event.from_dict(data[2])
                        except (TypeError, ValueError) as e:
                            continue
                        events.append(event)
                    elif data[0] == "EOSE" and data[1] == subscription_id:
                        await ws.send_str(json.dumps(["CLOSE", subscription_id]))
                        await asyncio.sleep(1)
                        break
                    elif data[0] == "CLOSED" and data[1] == subscription_id:
                        break
                elif msg.type == WSMsgType.ERROR:
                    print(f"WebSocket error: {msg.data}")
                    break
                elif msg.type == WSMsgType.CLOSED:
                    print("WebSocket closed")
                    break
                else:
                    print(f"Unexpected message type: {msg.type}")
                    break
    return events

if __name__ == "__main__":
    # Example usage
    relay = Relay("wss://relay.damus.io")
    events = asyncio.run(fetch_events(relay))
    for event in events:
        print(event)
    print(f"Fetched {len(events)} events.")
