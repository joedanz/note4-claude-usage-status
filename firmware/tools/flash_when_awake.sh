#!/usr/bin/env bash
# Flash the DevKit while it deep-sleeps: its USB port only exists for a few seconds per wake, so poll for it
# and flash the moment it appears. Run from firmware/ after `. ~/esp/esp-idf/export.sh`.
#   tools/flash_when_awake.sh [PORT]
PORT="${1:-/dev/cu.usbmodem1101}"
for try in 1 2 3 4; do
  echo "try $try: waiting for $PORT..."
  n=0
  until [ -e "$PORT" ] || [ "$n" -gt 400 ]; do sleep 0.25; n=$((n + 1)); done
  if [ -e "$PORT" ]; then
    out=$(idf.py -p "$PORT" -b 460800 flash 2>&1 | grep -E "Hash of data|^Done|Error|error|Failed" | tail -3 | cut -c1-140)
    echo "$out"
    echo "$out" | grep -q "^Done" && exit 0
  fi
done
echo "could not flash after 4 tries" >&2
exit 1
