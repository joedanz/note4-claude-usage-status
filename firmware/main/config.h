#pragma once
#include <cstddef>
#include <cstdint>

#include "secrets.local.h"  // WIFI_SSID, WIFI_PASS, SERVER_BASE, DEVICE_KEY

namespace cfg {
constexpr size_t kFrameBytes = 15000;
constexpr uint32_t kDefaultPollSeconds = 300;
constexpr uint32_t kRetrySeconds = 60;
constexpr int kQuickRetries = 3;
constexpr uint32_t kFastWifiTimeoutMs = 8000;
constexpr uint32_t kWifiTimeoutMs = 20000;
constexpr uint32_t kHttpTimeoutMs = 15000;
constexpr int kLowBatteryPercent = 10;
constexpr uint32_t kLowBatterySleepSeconds = 1800;
constexpr uint32_t kUnauthorizedSleepSeconds = 1800;
constexpr uint32_t kAwakeBudgetSeconds = 90;  // a wake that takes longer than this is abandoned (battery guard)
constexpr int kMaxPage = 2;  // pages 1..kMaxPage: usage, status
}  // namespace cfg
