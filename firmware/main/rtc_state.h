#pragma once
#include <cstdint>

// State that survives deep sleep (kept in RTC memory).
struct RtcState {
    uint32_t magic;
    uint8_t page;          // 1-based current page
    char etag[40];         // ETag of the frame currently on the panel for `page` ("" = unknown)
    uint8_t quick_retries;
    bool have_bssid;
    uint8_t wifi_channel;
    uint8_t bssid[6];
    uint32_t wake_count;
};

RtcState& RtcStateGet();  // zero-initialized on a cold boot
