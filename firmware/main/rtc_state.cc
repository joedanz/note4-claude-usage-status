#include "rtc_state.h"

#include <cstring>

#include "esp_attr.h"

namespace {
constexpr uint32_t kMagic = 0xC1AD0E01;
RTC_DATA_ATTR RtcState g_state;
}  // namespace

RtcState& RtcStateGet() {
    if (g_state.magic != kMagic) {
        std::memset(&g_state, 0, sizeof(g_state));
        g_state.magic = kMagic;
        g_state.page = 1;
    }
    return g_state;
}
