#include "fetch.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <strings.h>

#include "config.h"
#include "esp_http_client.h"
#include "esp_log.h"

namespace {
const char* kTag = "note4_claude";

struct Ctx {
    uint8_t* buf;
    size_t got;
    bool overflow;
    FetchOut* out;
};

esp_err_t OnHttp(esp_http_client_event_t* e) {
    auto* c = static_cast<Ctx*>(e->user_data);
    if (e->event_id == HTTP_EVENT_ON_HEADER) {
        if (strcasecmp(e->header_key, "ETag") == 0) {
            const char* v = e->header_value;
            if (*v == '"') ++v;
            std::strncpy(c->out->etag, v, sizeof(c->out->etag) - 1);
            char* q = std::strchr(c->out->etag, '"');
            if (q != nullptr) *q = '\0';
        } else if (strcasecmp(e->header_key, "X-Next-Poll") == 0) {
            c->out->next_poll_s = static_cast<uint32_t>(std::strtoul(e->header_value, nullptr, 10));
        }
    } else if (e->event_id == HTTP_EVENT_ON_DATA && esp_http_client_get_status_code(e->client) == 200) {
        if (c->got + static_cast<size_t>(e->data_len) <= cfg::kFrameBytes) {
            std::memcpy(c->buf + c->got, e->data, static_cast<size_t>(e->data_len));
            c->got += static_cast<size_t>(e->data_len);
        } else {
            c->overflow = true;
        }
    }
    return ESP_OK;
}
}  // namespace

FetchResult FetchPage(int page, const char* if_none_match, uint8_t* frame, FetchOut* out) {
    char url[128];
    std::snprintf(url, sizeof(url), "%s/v1/page/%d.bin", SERVER_BASE, page);
    Ctx ctx{frame, 0, false, out};
    esp_http_client_config_t hc = {};
    hc.url = url;
    hc.timeout_ms = cfg::kHttpTimeoutMs;
    hc.event_handler = OnHttp;
    hc.user_data = &ctx;
    hc.disable_auto_redirect = true;
    esp_http_client_handle_t client = esp_http_client_init(&hc);
    if (client == nullptr) return FetchResult::kFailed;
    esp_http_client_set_header(client, "X-Device-Key", DEVICE_KEY);
    char inm[64];
    if (if_none_match != nullptr && if_none_match[0] != '\0') {
        std::snprintf(inm, sizeof(inm), "\"%s\"", if_none_match);
        esp_http_client_set_header(client, "If-None-Match", inm);
    }
    const esp_err_t err = esp_http_client_perform(client);
    const int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    ESP_LOGI(kTag, "page=%d http=%d bytes=%u err=%s", page, status, static_cast<unsigned>(ctx.got),
             esp_err_to_name(err));
    if (err != ESP_OK) return FetchResult::kFailed;
    switch (status) {
        case 200:
            return (ctx.got == cfg::kFrameBytes && !ctx.overflow) ? FetchResult::kUpdated : FetchResult::kFailed;
        case 304: return FetchResult::kNotModified;
        case 404: return FetchResult::kNotFound;
        case 401: return FetchResult::kUnauthorized;
        default: return FetchResult::kFailed;
    }
}
