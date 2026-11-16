# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant add-on repository for Korean apartment wallpad control (EzVille).
The only add-on is `simple_mqtt_ezville_control` (this is what runs at home).
RS485 traffic reaches the add-on via EW11 (WiFi-to-RS485) over MQTT; HA integration is MQTT Discovery.

```
Wallpad ──RS485── EW11 ──MQTT ew11/recv──▶ add-on ──MQTT ezville/...──▶ HA
                       ◀──MQTT ew11/send──        ◀── ezville/.../command
```

The MQTT device name is `ezville_wallpad` (in `ezville.py`); HA entity IDs derive from it
(`light.ezville_wallpad_ezville_light_01_01`). Do not rename it.

## Layout

- `simple_mqtt_ezville_control/ezville.py`: whole add-on (single asyncio loop in `ezville_loop`)
- `simple_mqtt_ezville_control/config.json`: add-on version/options. Bump `version` or HA won't see updates.
- `simple_mqtt_ezville_control/PACKETS.md`: packet notes

## Key Functions (inside `ezville_loop`)

- `EW11_process(raw_hex)`: split packets, parse states, register discovery, `update_state`
- `HA_process(topics, value)`: HA command → RS485 packet → `CMD_QUEUE`
- `send_to_ew11(send_data)`: send + retry until `DEVICE_STATE` matches `statcmd`
- `checksum(hex)`: fills XOR/ADD bytes

## Packet Structure

```
[F7][device_id][room][cmd][len][data...][XOR][ADD]
```

Device IDs: light `0E`, thermostat `36`, plug `39`, gas valve `12`, batch `33`.

### Light dimming (measured 2026-11-16)
- Command data: `[light_no][level<<4 | 1][00]`, levels 1-4 (e.g. `41` = level 4)
- State byte: `level<<4 | 0x02 (dimmable flag) | on-bit`; off = `0x02`
- Dimmable lights are auto-detected from the `0x02` bit.

## Test

```bash
python3 simple_mqtt_ezville_control/test_dimming.py
```

## Language

Code comments and documentation are primarily in Korean.
