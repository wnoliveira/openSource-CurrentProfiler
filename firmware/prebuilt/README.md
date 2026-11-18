# Prebuilt firmware

**Status: In development.** These are existing build artifacts from the earlier
source snapshot, built with ESP-IDF 5.4.2 for **esp32**, 4 MB flash, DIO and a
40 MHz flash clock. They have not been rebuilt from the current readable-source
revision or tested on a physical board here. Build the current source in
[`firmware`](../README.md) to validate the changes.

| Flash address | File |
|---|---|
| 0x1000 | bootloader.bin |
| 0x8000 | partition-table.bin |
| 0x10000 | iot_current_scope.bin |

To flash these existing images, open an ESP-IDF terminal in this directory and
replace `COM5` with the board's port:

```powershell
python -m esptool --chip esp32 --port COM5 --baud 460800 --before default_reset --after hard_reset write_flash --flash_mode dio --flash_size 4MB --flash_freq 40m 0x1000 bootloader.bin 0x8000 partition-table.bin 0x10000 iot_current_scope.bin
```

Disconnect the desktop application before flashing. These images target the
original ESP32 and must not be used on ESP32-S2/S3/C3/C6 boards. Use
[`sha256.json`](sha256.json) to identify the exact images used in an experiment.

The images use SDA=21, SCL=22 and UART0 at 460,800 baud. Rebuild to change pins.
Project licensing and third-party distribution obligations are described in
the repository's [license](../../LICENSE) and [third-party notices](../../THIRD_PARTY.md).
