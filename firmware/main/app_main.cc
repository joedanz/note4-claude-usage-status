#include <cstring>

#include "config.h"
#include "esp_log.h"
#include "esp_sleep.h"
#include "esp_timer.h"
#include "fetch.h"
#include "freertos/FreeRTOS.h"
#include "nvs_flash.h"
#include "rtc_state.h"
#include "sleep.h"
#include "wifi.h"
#include "zectrix_board.h"
#include "zectrix_canvas.h"
#include "zectrix_epd.h"

namespace {
const char* kTag = "claude_eink";
ZectrixCanvas g_canvas;  // 15,000 bytes; the fetched frame lands in g_canvas.data()

// Every path below ends in DeepSleepFor, but a hang (panel, board init, a trickling server) would keep the radio
// and CPU on and flatten the battery in hours. This one-shot timer abandons any wake that outlasts its budget.
void ArmAwakeWatchdog() {
    esp_timer_create_args_t args = {};
    args.callback = [](void*) {
        ESP_LOGE(kTag, "awake budget of %u s exceeded; sleeping", static_cast<unsigned>(cfg::kAwakeBudgetSeconds));
        DeepSleepFor(cfg::kRetrySeconds);
    };
    args.name = "awake_watchdog";
    esp_timer_handle_t timer = nullptr;
    if (esp_timer_create(&args, &timer) == ESP_OK) {
        esp_timer_start_once(timer, static_cast<uint64_t>(cfg::kAwakeBudgetSeconds) * 1000000ULL);
    }
}
}  // namespace

extern "C" void app_main(void) {
    ArmAwakeWatchdog();
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    static ZectrixBoard board;
    if (board.Init() != ESP_OK) ESP_LOGE(kTag, "board init failed");
    board.SetAudioPower(false);  // not used; saves power

    zectrix_epd_config_t config = {};
    zectrix_epd_get_default_config(&config);
    zectrix_epd_handle_t epd = nullptr;
    ESP_ERROR_CHECK(zectrix_epd_new(&config, &epd));

    RtcState& st = RtcStateGet();
    st.wake_count++;
    const Wake wake = WakeReason();
    const bool button = (wake == Wake::kButtonOk || wake == Wake::kButtonDown);
    if (button) {
        // DOWN = next page, OK = previous page; both wrap within 1..kMaxPage.
        const int step = (wake == Wake::kButtonDown) ? 1 : cfg::kMaxPage - 1;
        st.page = static_cast<uint8_t>((st.page - 1 + step) % cfg::kMaxPage + 1);
        st.etag[0] = '\0';  // force a redraw of the newly selected page
    }
    ESP_LOGI(kTag, "wake #%u reason=%d page=%d (raw cause=%d ext1=0x%llx)", static_cast<unsigned>(st.wake_count),
             static_cast<int>(wake), st.page, static_cast<int>(esp_sleep_get_wakeup_cause()),
             static_cast<unsigned long long>(esp_sleep_get_ext1_wakeup_status()));

    uint32_t sleep_s = cfg::kDefaultPollSeconds;
    bool failed = false;

    const ZectrixPowerSnapshot power = board.ReadPowerSnapshot();
    const bool low_battery = power.battery_valid && power.battery_percent < cfg::kLowBatteryPercent;
    if (low_battery) ESP_LOGW(kTag, "battery %u%%", static_cast<unsigned>(power.battery_percent));

    if (!WifiConnect(cfg::kWifiTimeoutMs)) {
        ESP_LOGE(kTag, "wifi failed; keeping the current screen");
        WifiStop();  // the Wi-Fi task keeps retrying otherwise
        failed = true;
    } else {
        FetchOut out;
        FetchResult r = FetchResult::kFailed;
        for (int attempt = 0; attempt < cfg::kMaxPage; ++attempt) {
            out = FetchOut();
            r = FetchPage(st.page, st.etag, g_canvas.data(), &out);
            if (r != FetchResult::kNotFound || !button) break;
            st.page = static_cast<uint8_t>(st.page % cfg::kMaxPage + 1);  // skip a page the server does not have
            st.etag[0] = '\0';
        }
        switch (r) {
            case FetchResult::kUpdated: {
                if (low_battery) {  // overlay a white strip with black text along the bottom edge
                    g_canvas.FillRect(0, 282, 400, 18, false);
                    g_canvas.Text(8, 284, "LOW BATTERY - CHARGE SOON", 1, false);
                }
                esp_err_t d = zectrix_epd_power_on(epd);
                if (d == ESP_OK) d = zectrix_epd_refresh_full_1bpp(epd, g_canvas.data(), g_canvas.size());
                zectrix_epd_power_off(epd);
                std::strncpy(st.etag, out.etag, sizeof(st.etag) - 1);
                ESP_LOGI(kTag, "drew page %d: %s etag=%s", st.page, esp_err_to_name(d), st.etag);
                if (out.next_poll_s > 0) sleep_s = out.next_poll_s;
                break;
            }
            case FetchResult::kNotModified:
                if (out.next_poll_s > 0) sleep_s = out.next_poll_s;
                break;
            case FetchResult::kNotFound:  // the server is up but has no such page yet (e.g. just restarted)
                ESP_LOGW(kTag, "page %d not ready; keeping the screen and the stored etag", st.page);
                failed = true;
                break;
            case FetchResult::kUnauthorized:
                ESP_LOGE(kTag, "server rejected the device key; check DEVICE_KEY");
                sleep_s = cfg::kUnauthorizedSleepSeconds;
                break;
            case FetchResult::kFailed:
                failed = true;
                break;
        }
        WifiStop();
    }

    if (failed) {
        if (st.quick_retries < cfg::kQuickRetries) {
            st.quick_retries++;
            sleep_s = cfg::kRetrySeconds;
            ESP_LOGW(kTag, "quick retry %d/%d in %u s", st.quick_retries, cfg::kQuickRetries,
                     static_cast<unsigned>(sleep_s));
        } else {
            st.quick_retries = 0;  // give up quickly retrying; fall back to the normal cadence
        }
    } else {
        st.quick_retries = 0;
    }
    if (low_battery) sleep_s = cfg::kLowBatterySleepSeconds;
    DeepSleepFor(sleep_s);
}
