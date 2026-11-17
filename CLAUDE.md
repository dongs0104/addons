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

- `simple_mqtt_ezville_control/ezville.py`: `Wallpad` class — MQTT I/O, state cache, command retry loops (asyncio)
- `simple_mqtt_ezville_control/devices.py`: one class per device (`parse` / `discovery` / `command`), registry `DEVICES`
- `simple_mqtt_ezville_control/packet.py`: byte-level split / checksum / build
- `simple_mqtt_ezville_control/config.json`: add-on version/options. Bump `version` or HA won't see updates.
- `simple_mqtt_ezville_control/PACKETS.md`: packet notes
- `custom_components/korean_radio/`: HA custom integration (not an add-on). Korean radio via media browser + `media_player.korean_radio` (source = channel, sound mode = HomePod). Deployed by scp to `/config/custom_components/`; HLS → ffmpeg MP3 because HomePod (pyatv) can't play HLS.

## Data Flow

1. `ew11/recv` → `Wallpad.on_rs485` → `packet.split` (keeps partial tail in `residue`)
2. `DEVICES[id].parse(packet)` → `Reading`s → discovery (first time) + `update_state` (publish on change)
3. `ezville/<name>/<sub>/command` → `Device.command` → `Command(packet, key, target)` → `send` retries until `state[key] == target`

EW11 is MQTT-only (no socket mode).

## Packet Structure

```
[F7][device_id][room][cmd][len][data...][XOR][ADD]
```

Device IDs: light `0E`, thermostat `36`, plug `39`, gas valve `12`, energy meter `30` (room 03 = electricity), fan `32`.
Unparsed (meaning unknown): `30` room 02, `40`, `63`, `39` cmd `52`/`D2`.

### Light dimming (measured 2026-11-16)
- Command data: `[light_no][level<<4 | 1][00]`, levels 1-4 (e.g. `41` = level 4)
- State byte: `level<<4 | 0x02 (dimmable flag) | on-bit`; off = `0x02`
- Dimmable lights are auto-detected from the `0x02` bit.

## Test

```bash
cd simple_mqtt_ezville_control && python3 test_ezville.py  # real captured packets
```

## Language

Code comments and documentation are primarily in Korean.
