# NOTE4 DevKit firmware

An ESP-IDF 5.4 project for the monochrome ZECTRIX NOTE4 Developer Kit, derived from the MIT-licensed reference demo
(`LICENSE`, `THIRD_PARTY_NOTICES.md`, `licenses/`). It wakes, fetches one 15,000-byte frame from the collector's LAN server,
redraws only if it changed, and deep-sleeps.

## Build and flash (from the development Mac, DevKit connected by a data USB cable)

```bash
cp main/secrets.example.h main/secrets.local.h     # then fill it in yourself; it is git-ignored
. ~/esp/esp-idf/export.sh
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/cu.usbmodem1101 -b 460800 flash
python tools/serial_log.py --seconds 60 --reset     # watch the log (survives deep sleep)
```

While the firmware is running it deep-sleeps and the USB port disappears; it is only present for about 4 seconds per wake,
so `idf.py flash` can fail with "run_serial_tool" errors. Poll for `/dev/cu.usbmodem1101` and flash the moment it appears
(or hold BOOT and tap RESET to force download mode).

Back up the full 16 MB factory flash before the first flash, and keep a copy somewhere safe. Only flash the monochrome
NOTE4 Devkit, never the four-color NOTE4C.

```bash
esptool.py --chip esp32s3 -p /dev/cu.usbmodem1101 read_flash 0 0x1000000 factory-backup.bin   # back up
shasum -a 256 factory-backup.bin > factory-backup.bin.sha256
esptool.py --chip esp32s3 -p /dev/cu.usbmodem1101 write_flash 0 factory-backup.bin             # restore it later
```

Run these after `. ~/esp/esp-idf/export.sh` (ESP-IDF 5.4 ships esptool 4.x). Restoring the backup puts the original ZECTRIX
firmware back. For development without the real collector, run `scripts/dev_lan_server.py` from the repository root.

## Behavior

One cycle per wake: join Wi-Fi (remembered channel/BSSID first), `GET /v1/page/{page}.bin` with `X-Device-Key` and
`If-None-Match`, draw on `200`, do nothing on `304`, then deep sleep for the server's `X-Next-Poll` seconds (default 300).
The current page and the drawn ETag live in RTC memory across sleeps.

## Wake budget

A one-shot timer abandons any wake that lasts longer than `kAwakeBudgetSeconds` (90 s) and deep-sleeps for `kRetrySeconds`,
so a hang cannot drain the battery. A normal wake takes about 3.5 s, and the worst planned case (a failed fast reconnect plus a
full scan, a slow HTTP fetch and a panel refresh) is about 55 s.

## Measured on the hardware

- A wake-to-sleep cycle takes about 3.4 s; fast reconnect gets an IP about 2 s after wake (a cold join took about 8 s).
- Deep sleep with USB unplugged keeps the device powered: the wake counter kept advancing on battery alone, so the battery
  latch (GPIO17) holds through deep sleep when `gpio_deep_sleep_hold_en()` is called.
- Buttons: **OK** (previous page) and **DOWN** (next page) wake the device from deep sleep and redraw in about 4 s. **UP**
  (GPIO39) cannot wake it: only GPIO0-21 are RTC-capable on the ESP32-S3.
- A truncated body or a wrong device key never redraws the panel.
- Sleep current is not measured (no current meter), so battery life is an estimate.
