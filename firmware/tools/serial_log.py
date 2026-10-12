#!/usr/bin/env python3
"""Print the device's serial log, surviving the USB re-enumeration that deep sleep causes.

Run with the ESP-IDF environment (it provides pyserial):  . ~/esp/esp-idf/export.sh
  python firmware/tools/serial_log.py --seconds 60 --reset
"""
import argparse
import time

import serial

p = argparse.ArgumentParser()
p.add_argument("--port", default="/dev/cu.usbmodem1101")
p.add_argument("--seconds", type=float, default=30)
p.add_argument("--reset", action="store_true", help="pulse RTS once at the start to catch the boot log")
p.add_argument("--grep", default="claude_eink", help="only print lines containing this (empty = all)")
args = p.parse_args()

end = time.time() + args.seconds
ser, first = None, True
buf = b""
while time.time() < end:
    if ser is None:
        try:
            ser = serial.Serial(args.port, 115200, timeout=0.3)
            if first and args.reset:
                ser.dtr = False
                ser.rts = True
                time.sleep(0.1)
                ser.rts = False
            first = False
        except (serial.SerialException, OSError):
            time.sleep(0.5)  # the port disappears while the chip sleeps and returns when it wakes
            continue
    try:
        buf += ser.read(4096)
    except (serial.SerialException, OSError):
        ser = None
        continue
    while b"\n" in buf:
        line, buf = buf.split(b"\n", 1)
        text = line.decode("utf-8", "replace").rstrip()
        if text and (not args.grep or args.grep in text):
            print(f"{time.strftime('%H:%M:%S')} {text}", flush=True)
