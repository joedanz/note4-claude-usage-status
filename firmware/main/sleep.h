#pragma once
#include <cstdint>

enum class Wake { kCold, kTimer, kButtonOk, kButtonDown, kOther };

Wake WakeReason();
[[noreturn]] void DeepSleepFor(uint32_t seconds);
