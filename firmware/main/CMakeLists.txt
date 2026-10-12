idf_component_register(SRCS "app_main.cc" "wifi.cc" "fetch.cc" "rtc_state.cc" "sleep.cc"
                       REQUIRES
                       zectrix_board
                       zectrix_epd
                       zectrix_canvas
                       driver
                       esp_event
                       esp_http_client
                       esp_netif
                       esp_wifi
                       esp_timer
                       nvs_flash)
