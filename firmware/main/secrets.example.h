// Copy to secrets.local.h (git-ignored) and fill in. Never commit or paste the real file.
// The ESP32-S3 joins 2.4 GHz networks only, and SSIDs are case-sensitive.
#pragma once
#define WIFI_SSID "YOUR_WIFI_NAME"
#define WIFI_PASS "YOUR_WIFI_PASSWORD"
#define SERVER_BASE "http://192.168.1.50:8099"            // the collector Mac's reserved LAN address
#define DEVICE_KEY "PASTE_OUTPUT_OF_claude-eink_device-key"
