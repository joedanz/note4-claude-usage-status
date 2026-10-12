#!/usr/bin/env python3
"""Serve sample pages over the real LAN protocol, for firmware development. No login or device needed.

  .venv/bin/python scripts/dev_lan_server.py --key dev-key --poll 20 --tick 45
Options: --poll S     value of X-Next-Poll the device is told (default 300)
         --tick S     alternates page 1 between two different pictures every S seconds (so the ETag changes)
         --truncate   serves a short body (checks the firmware refuses it)
         --skip N     do not serve page N (repeatable): simulates a just-restarted daemon with an empty store
"""
import argparse
import hashlib
import threading
import time

from claude_eink.config import Config
from claude_eink.lan import FRAME_BYTES, LanSink
from claude_eink.lan_server import detect_lan_ip, make_server
from claude_eink.sample import sample_pngs

p = argparse.ArgumentParser()
p.add_argument("--host", default="")
p.add_argument("--port", type=int, default=Config().lan_port)
p.add_argument("--key", default="dev-key")
p.add_argument("--poll", type=int, default=300)
p.add_argument("--tick", type=float, default=0)
p.add_argument("--truncate", action="store_true")
p.add_argument("--skip", type=int, action="append", default=[])
args = p.parse_args()

sink = LanSink()
pngs = sample_pngs()
usage_png, status_png = pngs["usage"], pngs["status"]
if 1 not in args.skip:
    sink.push(1, usage_png, hashlib.sha256(usage_png).hexdigest())
if 2 not in args.skip:
    sink.push(2, status_png, hashlib.sha256(status_png).hexdigest())

server = make_server(sink, args.host or detect_lan_ip(), args.port, args.key, args.poll)

if args.truncate:
    handler_cls = server.RequestHandlerClass
    real_do_get = handler_cls.do_GET

    def do_GET(self):
        frame = sink.get(1)
        if self.path.startswith("/v1/page/1.bin") and self.headers.get("X-Device-Key") == args.key and frame:
            self.send_response(200)
            self.send_header("Content-Length", str(FRAME_BYTES))
            self.end_headers()
            self.wfile.write(frame.data[:7000])      # promise a full frame, send less than half, then close
            self.close_connection = True
            return
        real_do_get(self)

    handler_cls.do_GET = do_GET

if args.tick:
    def ticker():
        n = 0
        while True:
            time.sleep(args.tick)
            n += 1
            sink.push(1, usage_png if n % 2 else status_png, f"tick-{n}")   # a different picture changes the ETag

    threading.Thread(target=ticker, daemon=True).start()

host, port = server.server_address[:2]
print(f"serving sample pages on http://{host}:{port}  (device key: {args.key})", flush=True)
server.serve_forever()
