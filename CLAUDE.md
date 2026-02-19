# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant add-on for Korean apartment wallpad control (EzVille).
RS485 communication with wallpad uses MQTT via EW11 (WiFi-to-RS485 converter).
HA integration uses standard MQTT Discovery (automatic as HA add-on).

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          MQTT Broker                                │
└─────────────────────────────────────────────────────────────────────┘
       ▲                    ▲                           ▲
       │ ew11/recv          │ ew11/send                 │ ezville/...
       │ (RS485 rx)         │ (RS485 tx)                │ homeassistant/...
       │                    │                           │
┌──────┴──────┐      ┌──────┴───────────────────────────┴──────┐
│    EW11     │      │              This Addon                 │
│ (RS485-WiFi)│      │  - Parse RS485 packets                  │
└──────┬──────┘      │  - Control wallpad devices              │
       │             │  - Publish states to HA                 │
    RS485            └─────────────────────────────────────────┘
       │
┌──────┴──────┐
│  Wallpad    │
│ (Light,     │
│  Thermostat,│
│  etc.)      │
└─────────────┘
```

## Build and Run Commands

### Docker (Home Assistant Add-on)
```bash
docker build -t ezville_wallpad ./ezville_wallpad
docker run ezville_wallpad
```

### Standalone Mode
```bash
cd ezville_wallpad
./run_standalone.sh  # First run generates options_standalone.json
```

### Dependencies
- Python 3.10+
- paho-mqtt

### Code Formatting
```bash
black .
```

## Key Configuration (`config.json`)

```json
{
    "rs485_mqtt": {
        "recv_topic": "ew11/recv",  // EW11 → Addon: raw RS485 packets from wallpad
        "send_topic": "ew11/send"   // Addon → EW11: commands to wallpad
    },
    "mqtt": {
        "server": "...",
        "prefix": "ezville"  // Topic prefix for HA integration (ezville/light/..., etc.)
    },
    "watchdog": {
        "timeout": 60  // Alert if no RS485 packet received (seconds)
    }
}
```

### MQTT Topics (RS485 Communication)
| Topic | Direction | Purpose |
|-------|-----------|---------|
| `ew11/recv` | EW11 → Addon | Raw RS485 packets from wallpad |
| `ew11/send` | Addon → EW11 | RS485 commands to wallpad |

HA integration topics (`ezville/...`, `homeassistant/...`) follow standard MQTT Discovery conventions.

## Core Module: `ezville_wallpad/ezville_wallpad.py`

### Data Flow
1. **MQTT Receive** (`mqtt_on_rs485_recv`): EW11 publishes RS485 data to `ew11/recv`
2. **Packet Buffer** (`PacketBuffer`): Buffers and extracts complete packets (starts with `0xF7`)
3. **Packet Processing** (`process_single_packet`): Parses state responses, handles ACKs
4. **HA Publish** (`serial_receive_state`): Publishes device states to `ezville/{device}/{id}/state`

### Packet Structure
```
[0xF7][device_id][room_id][cmd][length][data...][XOR checksum][ADD checksum]
```

### Device IDs
- Light: `0x0E`
- Thermostat: `0x36`
- Gas valve: `0x12`
- Plug: `0x50`
- Batch: `0x33`

### Key Functions
- `rs485_send(packet)`: Send command via MQTT to EW11
- `process_packets()`: Extract and process packets from buffer
- `serial_verify_checksum()`: Validate packet checksum
- `watchdog_loop()`: Monitor packet reception, clear stale commands

## Language

Code comments and documentation are primarily in Korean.
