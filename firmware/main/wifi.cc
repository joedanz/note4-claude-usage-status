#include "wifi.h"

#include <cstring>

#include "config.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "rtc_state.h"

namespace {
const char* kTag = "note4_claude";
constexpr int kConnectedBit = BIT0;
constexpr int kFailedBit = BIT1;
EventGroupHandle_t g_events;
bool g_inited = false;
int g_retries = 0;
int g_max_retries = 0;

void OnEvent(void*, esp_event_base_t base, int32_t id, void* data) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const auto* d = static_cast<wifi_event_sta_disconnected_t*>(data);
        if (d->reason != WIFI_REASON_ASSOC_LEAVE) ESP_LOGW(kTag, "wifi disconnected reason=%d", d->reason);
        if (g_retries++ < g_max_retries) {
            esp_wifi_connect();
        } else {
            xEventGroupSetBits(g_events, kFailedBit);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        wifi_ap_record_t ap;
        if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
            RtcState& st = RtcStateGet();
            st.wifi_channel = ap.primary;
            std::memcpy(st.bssid, ap.bssid, sizeof(st.bssid));
            st.have_bssid = true;
        }
        const auto* ev = static_cast<ip_event_got_ip_t*>(data);
        ESP_LOGI(kTag, "got ip " IPSTR, IP2STR(&ev->ip_info.ip));
        xEventGroupSetBits(g_events, kConnectedBit);
    }
}

void EnsureInit() {
    if (g_inited) return;
    g_events = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &OnEvent, nullptr));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &OnEvent, nullptr));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    g_inited = true;
}

bool Attempt(bool fast, uint32_t timeout_ms) {
    wifi_config_t wc = {};
    std::strncpy(reinterpret_cast<char*>(wc.sta.ssid), WIFI_SSID, sizeof(wc.sta.ssid) - 1);
    std::strncpy(reinterpret_cast<char*>(wc.sta.password), WIFI_PASS, sizeof(wc.sta.password) - 1);
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;  // WPA2 or WPA2/WPA3 transition
    RtcState& st = RtcStateGet();
    if (fast) {
        wc.sta.channel = st.wifi_channel;
        wc.sta.bssid_set = true;
        std::memcpy(wc.sta.bssid, st.bssid, sizeof(wc.sta.bssid));
    }
    g_retries = 0;
    g_max_retries = fast ? 1 : 6;
    xEventGroupClearBits(g_events, kConnectedBit | kFailedBit);
    esp_wifi_stop();
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    const EventBits_t bits = xEventGroupWaitBits(g_events, kConnectedBit | kFailedBit, pdFALSE, pdFALSE,
                                                 pdMS_TO_TICKS(timeout_ms));
    return (bits & kConnectedBit) != 0;
}
}  // namespace

bool WifiConnect(uint32_t full_timeout_ms) {
    EnsureInit();
    const RtcState& st = RtcStateGet();
    if (st.have_bssid && st.wifi_channel != 0) {
        if (Attempt(true, cfg::kFastWifiTimeoutMs)) return true;
        ESP_LOGW(kTag, "fast reconnect failed; scanning");
        RtcStateGet().have_bssid = false;
    }
    return Attempt(false, full_timeout_ms);
}

void WifiStop() { esp_wifi_stop(); }
