import argparse
import asyncio
import json
import socket
import threading
import queue
import aiohttp
import numpy as np
import sounddevice as sd

# Audio settings
DEFAULT_SAMPLE_RATE = 48000
CHANNELS = 1
DTYPE = 'int16'
FRAME_SIZE = 1024  # samples per packet


def udp_sender_loop(sock: socket.socket, target, send_q: queue.Queue):
    while True:
        data = send_q.get()
        if data is None:
            break
        try:
            sock.sendto(data, target)
        except Exception:
            pass


def audio_input_callback(indata, frames, time, status, send_q: queue.Queue):
    send_q.put(indata.tobytes())


class PlaybackBuffer:
    def __init__(self):
        self.q = queue.Queue()

    def write(self, outdata):
        try:
            data = self.q.get_nowait()
            arr = np.frombuffer(data, dtype=DTYPE).reshape(-1, CHANNELS)

            if arr.size < outdata.size:
                outdata[:arr.size] = arr
                outdata[arr.size:] = 0
            else:
                outdata[:] = arr[:outdata.size]
        except queue.Empty:
            outdata.fill(0)


def get_device_sample_rate(device_id, is_input=True):
    try:
        device_info = sd.query_devices(device_id)
        if 'default_samplerate' in device_info:
            return int(device_info['default_samplerate'])
        return DEFAULT_SAMPLE_RATE
    except Exception:
        return DEFAULT_SAMPLE_RATE


async def run_client(args, stop_event, chat_recv_cb=None, chat_send_q=None):
    input_sample_rate = get_device_sample_rate(args.input_device, is_input=True)
    output_sample_rate = get_device_sample_rate(args.output_device, is_input=False)
    sample_rate = min(input_sample_rate, output_sample_rate)

    print(f"INPUT DEVICE: {args.input_device}, SAMPLE RATE: {input_sample_rate} Hz")
    print(f"OUTPUT DEVICE: {args.output_device}, SAMPLE RATE: {output_sample_rate} Hz")
    print(f"USING SAMPLE RATE: {sample_rate} Hz")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind_ip, args.bind_port))
    local_port = sock.getsockname()[1]

    print('Ожидание пиров...')

    peers = []

    if chat_send_q is None:
        chat_send_q = queue.Queue()

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(args.server) as ws:
            await ws.send_json({
                'type': 'register',
                'room': args.room,
                'id': args.id,
                'udp_port': local_port
            })

            async def chat_sender():
                while True:
                    text = await asyncio.get_event_loop().run_in_executor(None, chat_send_q.get)
                    if text is None:
                        break
                    await ws.send_json({'type': 'chat', 'text': text})

            chat_sender_task = asyncio.create_task(chat_sender())

            got_peers = False

            async def message_handler():
                nonlocal got_peers, peers
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    data = json.loads(msg.data)
                    if data.get('type') == 'peers' and data.get('peers'):
                        peers = data['peers']
                        got_peers = True
                        print(f"Есть пиры: {peers}")
                    elif data.get('type') == 'chat':
                        print(f"[CHAT {data['from']}]: {data['text']}")
                        if chat_recv_cb:
                            chat_recv_cb(data['from'], data['text'])

            message_handler_task = asyncio.create_task(message_handler())

            while not got_peers and not stop_event.is_set():
                await asyncio.sleep(0.1)

            if stop_event.is_set():
                chat_send_q.put(None)
                message_handler_task.cancel()
                await chat_sender_task
                return

            if not peers:
                print("No peers found")
                chat_send_q.put(None)
                message_handler_task.cancel()
                await chat_sender_task
                return

            peer = peers[0]
            target = (peer['ip'], int(peer['udp_port']))
            print(f'Peer discovered: {target}, starting hole-punching')

            send_q = queue.Queue()
            sender_thread = threading.Thread(target=udp_sender_loop, args=(sock, target, send_q), daemon=True)
            sender_thread.start()

            playback = PlaybackBuffer()
            out_stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=FRAME_SIZE,
                device=args.output_device,
                callback=lambda outdata, frames, time, status: playback.write(outdata)
            )
            out_stream.start()

            in_stream = sd.InputStream(
                samplerate=sample_rate,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=FRAME_SIZE,
                device=args.input_device,
                callback=lambda indata, frames, time, status:
                    audio_input_callback(indata.copy(), frames, time, status, send_q)
            )
            in_stream.start()

            def udp_recv_loop(s, playback_buf):
                while True:
                    try:
                        data, addr = s.recvfrom(65536)
                        playback_buf.q.put(data)
                    except Exception:
                        break

            recv_thread = threading.Thread(target=udp_recv_loop, args=(sock, playback), daemon=True)
            recv_thread.start()

            for i in range(6):
                sock.sendto(b'PING', target)

            print('Streaming audio. Press Ctrl-C to quit.')

            try:
                while not stop_event.is_set():
                    await asyncio.sleep(0.2)
            except KeyboardInterrupt:
                pass
            finally:
                message_handler_task.cancel()
                chat_send_q.put(None)
                try:
                    await asyncio.gather(chat_sender_task, return_exceptions=True)
                except:
                    pass
                send_q.put(None)
                if in_stream:
                    in_stream.stop()
                if out_stream:
                    out_stream.stop()
                sock.close()


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--server', default='ws://localhost:8080/ws', help='Rendezvous server ws URL')
    p.add_argument('--room', required=True, help='Room name')
    p.add_argument('--id', required=True, help='Peer id')
    p.add_argument('--bind-ip', default='0.0.0.0', help='Local UDP bind IP')
    p.add_argument('--bind-port', type=int, default=0, help='Local UDP bind port (0 = auto)')
    p.add_argument('--input-device', type=int, default=None, help='Input audio device index')
    p.add_argument('--output-device', type=int, default=None, help='Output audio device index')
    return p.parse_args()


def main():
    args = parse_args()
    stop_event = threading.Event()
    asyncio.run(run_client(args, stop_event))


def start_peer(
    server_url,
    room,
    peer_id,
    bind_ip,
    bind_port,
    input_device,
    output_device,
    stop_event,
    chat_recv_cb=None,
    chat_send_q=None
):
    class Args:
        pass
    args = Args()
    args.server = server_url
    args.room = room
    args.id = peer_id
    args.bind_ip = bind_ip
    args.bind_port = int(bind_port)
    args.input_device = input_device
    args.output_device = output_device

    def run_peer():
        def local_chat_recv(sender, text):
            if chat_recv_cb:
                chat_recv_cb(sender, text)
        asyncio.run(run_client(args, stop_event, chat_recv_cb=local_chat_recv, chat_send_q=chat_send_q))

    peer_thread = threading.Thread(target=run_peer, daemon=True)
    peer_thread.start()
    return peer_thread


if __name__ == '__main__':
    main()