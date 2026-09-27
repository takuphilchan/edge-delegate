# Reference-device procurement proposal

[Roadmap](roadmap.md) | [Release contract](release-contract.md)

Status: proposed reference assembly revision A; not purchased, wired or qualified.
Owner approval of supplier, exact module revisions, shipping and budget is required before buying.
Prices are intentionally not invented. Hardware absence does not block software work.

| Item | Quantity proposed | Purpose / approval check |
| --- | ---: | --- |
| ESP32-S3-DevKitC-1-N8R8 | 2 | One reference board plus replacement/power-cut test board; record PCB revision |
| Genuine DS18B20 | 2 | Powered sensor plus spare; record package/pinout and source |
| SSD1306 I2C display module, verified 3.3 V compatible | 2 | Select exact module, dimensions and pull-up arrangement before wiring |
| Sensor pull-up resistor and wiring/prototyping supplies | 1 set | Value/wiring finalized against actual bus and sensor datasheet |
| USB data cables compatible with selected board revision | 2 | Use USB-to-UART port, not a charge-only cable |
| Independent reference thermometer | 1 | Record calibration/uncertainty suitable for acceptance envelope |
| Controlled USB power interruption fixture | 1 | Reproducible power-cut testing; approve electrical setup separately |

The board exposes an onboard USB-to-UART bridge. Check the purchased revision rather than
assuming all ESP32-S3 development boards have identical ports or pin assignments.
[Espressif board guide](https://documentation.espressif.com/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.0.html)

Use externally powered (not parasite-powered) fresh DS18B20 conversions at 9-bit resolution:
0.5 degrees C steps and specified maximum conversion time 93.75 ms, versus 750 ms at 12 bits.
Resolution is not assembled-system accuracy. Qualify measurements against the independent reference.
[DS18B20 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/DS18B20.pdf)

## Firmware/transport contract before wiring qualification

- Pin ESP-IDF, firmware hash, BOM/wiring revision and build tools. Disable Wi-Fi/Bluetooth.
- Stable identity plus boot/storage epochs; bounded serial frames and verified operation fingerprints.
- Durable intent before effect; receipt reconciliation; session fencing and rejection of conflicting duplicates.
- Conservative host-to-MCU deadline conversion with measured clock-offset uncertainty and boot epoch.
- Retain unknown outcomes after interrupted commits. Never erase receipt storage to clear a fault.
- A display ACK attests firmware completion, not visible pixels; independently record output.

NVS recovery can lose the value being written when power is interrupted. Tests must cover
interrupted writes, full storage and wear; absence of a receipt is not proof of no physical effect.
[Espressif NVS documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/storage/nvs_flash.html)

Before procurement: owner supplies delivery region/budget and approves exact SKUs. Before support:
freeze electrical/ambient limits, reference measurement procedure and acceptance tests. No firmware
or USB hardware-support claim is made by this proposal.
