idf_component_register(SRCS "main.c" "scope_core.c" INCLUDE_DIRS "."
    REQUIRES esp_driver_i2c esp_driver_uart esp_driver_gpio esp_timer nvs_flash esp_hw_support)
