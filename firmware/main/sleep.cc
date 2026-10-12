#include "sleep.h"

#include "driver/gpio.h"
#include "driver/rtc_io.h"
#include "esp_log.h"
#include "esp_sleep.h"
#include "zectrix_board_config.h"

namespace {
constexpr uint64_t kOkMask = 1ULL << ZECTRIX_BUTTON_OK;
constexpr uint64_t kDownMask = 1ULL << ZECTRIX_BUTTON_DOWN;

void PrepareButton(gpio_num_t pin) {
    rtc_gpio_init(pin);
    rtc_gpio_set_direction(pin, RTC_GPIO_MODE_INPUT_ONLY);
    rtc_gpio_pulldown_dis(pin);
    rtc_gpio_pullup_en(pin);  // buttons are active-low
}
}  // namespace

Wake WakeReason() {
    switch (esp_sleep_get_wakeup_cause()) {
        case ESP_SLEEP_WAKEUP_UNDEFINED: return Wake::kCold;
        case ESP_SLEEP_WAKEUP_TIMER: return Wake::kTimer;
        case ESP_SLEEP_WAKEUP_EXT1: {
            const uint64_t status = esp_sleep_get_ext1_wakeup_status();
            if (status & kDownMask) return Wake::kButtonDown;
            if (status & kOkMask) return Wake::kButtonOk;
            return Wake::kOther;
        }
        default: return Wake::kOther;
    }
}

void DeepSleepFor(uint32_t seconds) {
    ESP_LOGI("note4_claude", "deep sleep for %u s", static_cast<unsigned>(seconds));
    esp_sleep_enable_timer_wakeup(static_cast<uint64_t>(seconds) * 1000000ULL);
    PrepareButton(ZECTRIX_BUTTON_OK);
    PrepareButton(ZECTRIX_BUTTON_DOWN);
    esp_sleep_enable_ext1_wakeup_io(kOkMask | kDownMask, ESP_EXT1_WAKEUP_ANY_LOW);
    gpio_deep_sleep_hold_en();
    esp_deep_sleep_start();
}
