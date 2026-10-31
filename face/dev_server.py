"""Local stand-in for the backend side of the face contract.

`serve` hosts face/ over HTTP and a WebSocket hub at /ws on the same port. Every frame a client
sends is relayed to every other client, so the face page (or face_bot.py) and the CLI below can
talk without the real backend. Nothing here is used in production.

    python face/dev_server.py serve
    open 'http://127.0.0.1:8765/?ws=ws://127.0.0.1:8765/ws&debug=1'
    python face/dev_server.py send '{"type":"state","state":"thinking"}'
    python face/dev_server.py speak hello.wav --text "Hello, I'm Cue" --stream-ms 400
    python face/dev_server.py send '{"type":"stop"}'
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import mimetypes
import sys
import uuid
import wave
from http import HTTPStatus
from pathlib import Path
from urllib.parse import unquote, urlsplit

from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

FACE_DIR = Path(__file__).resolve().parent
DEFAULT_URL = "ws://127.0.0.1:8765/ws"
MAX_FRAME = 16 * 1024 * 1024  # base64 speech chunks can be large

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".js")


def static_response(connection: ServerConnection, request: Request) -> Response | None:
    path = urlsplit(request.path).path
    if path == "/ws":
        return None  # continue with the WebSocket handshake
    relative = unquote(path).lstrip("/") or "index.html"
    target = (FACE_DIR / relative).resolve()
    hidden = any(part.startswith(".") for part in target.relative_to(FACE_DIR).parts) if target.is_relative_to(FACE_DIR) else True
    if hidden or not target.is_file() or target.suffix == ".py":
        return connection.respond(HTTPStatus.NOT_FOUND, "Not found\n")
    body = target.read_bytes()
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    headers = Headers([("Content-Type", content_type), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
    return Response(HTTPStatus.OK, "OK", headers, body)


async def run_server(host: str, port: int) -> None:
    clients: set[ServerConnection] = set()

    async def hub(ws: ServerConnection) -> None:
        clients.add(ws)
        print(f"[hub] client connected ({len(clients)} total)", flush=True)
        try:
            async for frame in ws:
                summary = summarize(frame)
                print(f"[hub] {summary}", flush=True)
                for other in list(clients):
                    if other is not ws:
                        try:
                            await other.send(frame)
                        except ConnectionClosed:
                            clients.discard(other)
        finally:
            clients.discard(ws)
            print(f"[hub] client left ({len(clients)} total)", flush=True)

    async with serve(hub, host, port, process_request=static_response, max_size=MAX_FRAME):
        print(f"Face page:  http://{host}:{port}/?mock=1", flush=True)
        print(f"Live page:  http://{host}:{port}/?ws=ws://{host}:{port}/ws&debug=1", flush=True)
        print(f"Event hub:  ws://{host}:{port}/ws", flush=True)
        await asyncio.Future()


def summarize(frame: str | bytes) -> str:
    try:
        event = json.loads(frame)
    except (TypeError, ValueError):
        return f"non-JSON frame ({len(frame)} bytes)"
    if isinstance(event, dict) and isinstance(event.get("audio"), str):
        event = {**event, "audio": f"<{len(event['audio'])} base64 chars>"}
    return json.dumps(event)[:300]


async def send_events(url: str, events: list[dict], delays: list[float] | None = None, listen: float = 0.0) -> None:
    async with connect(url, max_size=MAX_FRAME) as ws:
        for index, event in enumerate(events):
            if delays and index < len(delays) and delays[index] > 0:
                await asyncio.sleep(delays[index])
            await ws.send(json.dumps(event))
        deadline = asyncio.get_running_loop().time() + listen
        while listen and (remaining := deadline - asyncio.get_running_loop().time()) > 0:
            try:
                print(summarize(await asyncio.wait_for(ws.recv(), remaining)), flush=True)
            except TimeoutError:
                break


def speak_events(path: Path, text: str, utterance_id: str, stream_ms: int) -> tuple[list[dict], list[float]]:
    """A whole file as one chunk, or a WAV split into pcm_s16le chunks to mimic streaming TTS."""
    if stream_ms <= 0 or path.suffix.lower() != ".wav":
        audio = base64.b64encode(path.read_bytes()).decode()
        fmt = path.suffix.lower().lstrip(".") or "wav"
        return [{"type": "speak", "id": utterance_id, "format": fmt, "audio": audio, "text": text, "final": True}], [0.0]
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise SystemExit("Streaming needs a 16-bit PCM WAV")
        rate, channels = wav.getframerate(), wav.getnchannels()
        frames_per_chunk = max(1, rate * stream_ms // 1000)
        chunks = []
        while data := wav.readframes(frames_per_chunk):
            chunks.append(data)
    events, delays = [], []
    for seq, data in enumerate(chunks):
        events.append(
            {
                "type": "speak",
                "id": utterance_id,
                "seq": seq,
                "final": seq == len(chunks) - 1,
                "format": "pcm_s16le",
                "sample_rate": rate,
                "channels": channels,
                "audio": base64.b64encode(data).decode(),
                **({"text": text} if seq == 0 else {}),
            }
        )
        # Send slightly faster than real time, the way a streaming TTS would.
        delays.append(0.0 if seq == 0 else stream_ms / 1000 * 0.8)
    return events, delays


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    serve_cmd = sub.add_parser("serve", help="serve face/ and the event hub")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8765)
    send_cmd = sub.add_parser("send", help="send one or more JSON events")
    send_cmd.add_argument("events", nargs="+", help="JSON objects, sent in order")
    send_cmd.add_argument("--url", default=DEFAULT_URL)
    send_cmd.add_argument("--gap", type=float, default=0.0, help="seconds between events")
    send_cmd.add_argument("--listen", type=float, default=0.0, help="print replies for N seconds")
    speak_cmd = sub.add_parser("speak", help="send an audio file as a speak event")
    speak_cmd.add_argument("file", type=Path)
    speak_cmd.add_argument("--text", default="")
    speak_cmd.add_argument("--id", default=None)
    speak_cmd.add_argument("--stream-ms", type=int, default=0, help="split a 16-bit WAV into PCM chunks of this length")
    speak_cmd.add_argument("--interrupt", action="store_true")
    speak_cmd.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args(argv)

    if args.command == "serve":
        try:
            asyncio.run(run_server(args.host, args.port))
        except KeyboardInterrupt:
            pass
    elif args.command == "send":
        try:
            events = [json.loads(raw) for raw in args.events]
        except ValueError as error:
            sys.exit(f"Invalid JSON: {error}")
        asyncio.run(send_events(args.url, events, [args.gap] * len(events), args.listen))
    else:
        events, delays = speak_events(args.file, args.text, args.id or f"utt-{uuid.uuid4().hex[:8]}", args.stream_ms)
        events[0]["interrupt"] = args.interrupt
        asyncio.run(send_events(args.url, events, delays))


if __name__ == "__main__":
    main()
