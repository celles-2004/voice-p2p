import argparse
import asyncio
import json
import logging
from aiohttp import web, WSMsgType

# Minimal INFO logging for server events
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

rooms = {}  # room -> list of peers ({'id', 'ws', 'udp_port', 'remote'})


async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    peer = None
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                t = data.get('type')
                if t == 'register':
                    room = data.get('room')
                    pid = data.get('id')
                    udp_port = data.get('udp_port')
                    if not room or not pid or udp_port is None:
                        await ws.send_json({'type': 'error', 'message': 'missing fields'})
                        continue

                    remote_ip = request.remote
                    peer = {'id': pid, 'ws': ws, 'udp_port': int(udp_port), 'remote': remote_ip, 'room': room}
                    rooms.setdefault(room, []).append(peer)
                    logging.info(f"Register: {pid} @ {remote_ip}:{udp_port} room={room}")
                    await notify_room(room)
                elif t == 'list':
                    await ws.send_json({'type': 'rooms', 'rooms': list(rooms.keys())})
                elif t == 'chat':
                    print("SERVER CHAT:", peer["id"], data.get("text"))
                    room = peer['room']
                    msg = {
                        'type': 'chat',
                        'from': peer['id'],
                        'text': data.get('text', '')
                    }

                    for p in rooms.get(room, []):
                        if p is not peer:
                            await p['ws'].send_json(msg)
                else:
                    await ws.send_json({'type': 'error', 'message': 'unknown type'})
            elif msg.type == WSMsgType.ERROR:
                print('ws connection closed with exception %s' % ws.exception())
    finally:
        if peer:
            room = peer.get('room')
            if room and peer in rooms.get(room, []):
                rooms[room].remove(peer)
                logging.info(f"Removed peer {peer.get('id')} from room {room}")
                if not rooms[room]:
                    del rooms[room]
                else:
                    await notify_room(room)

    return ws


async def notify_room(room):
    """Notify all peers in the room about other peers' public addresses."""
    peers = rooms.get(room, [])
    info = []
    for p in peers:
        info.append({'id': p['id'], 'ip': p['remote'], 'udp_port': p['udp_port']})

    for p in peers:
        try:
            await p['ws'].send_json({'type': 'peers', 'peers': [x for x in info if x['id'] != p['id']]})
        except Exception:
            pass


async def index(request):
    return web.Response(text='Rendezvous server for UDP hole-punching')


async def create_server_runner(port: int):
    """Create and start the aiohttp AppRunner and return it. Use this when embedding the server in another process."""
    app = web.Application()
    app.router.add_get('/', index)
    app.router.add_get('/ws', websocket_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f'Started rendezvous server on port {port} (in-process)')
    return runner


async def stop_server_runner(runner: web.AppRunner):
    """Clean up the runner created by `create_server_runner`."""
    try:
        await runner.cleanup()
        logging.info('Stopped rendezvous server (in-process)')
    except Exception:
        pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=8080, help='Port to listen on')
    args = p.parse_args()

    app = web.Application()
    app.router.add_get('/', index)
    app.router.add_get('/ws', websocket_handler)
    logging.info(f'Starting rendezvous server on port {args.port}')
    web.run_app(app, port=args.port)


if __name__ == '__main__':
    main()
