#pragma once
#include <cstdint>

// Joins the configured network. Tries the remembered channel/BSSID first (fast), then a full scan.
bool WifiConnect(uint32_t full_timeout_ms);
void WifiStop();
