#pragma once
#include <cstddef>
#include <cstdint>

enum class FetchResult { kUpdated, kNotModified, kNotFound, kUnauthorized, kFailed };

struct FetchOut {
    char etag[40] = {0};
    uint32_t next_poll_s = 0;  // 0 = the server did not say
};

// GET {SERVER_BASE}/v1/page/{page}.bin. `if_none_match` may be "" (unconditional).
// On kUpdated, exactly cfg::kFrameBytes bytes are in `frame`; nothing else is ever a success.
FetchResult FetchPage(int page, const char* if_none_match, uint8_t* frame, FetchOut* out);
