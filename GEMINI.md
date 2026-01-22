# Gemini Context: EzVille Wallpad Add-on

This project is a Home Assistant Add-on designed to control EzVille Wallpads via RS485 communication. It allows integration of lighting, heating, and other home automation features into Home Assistant using MQTT.

## Project Overview

*   **Purpose:** Interface with EzVille Wallpads using RS485 to control home devices (lights, thermostat, gas valve, etc.) from Home Assistant.
*   **Core Technology:** Python 3.10+, MQTT (Paho), Serial Communication (PySerial).
*   **Architecture:**
    *   **Core Logic:** `ezville_wallpad/ezville_wallpad.py` handles the RS485 protocol (via Serial or Socket/EW11), maintains device state, and communicates with Home Assistant via MQTT.
    *   **Configuration:** Uses standard Home Assistant Add-on configuration (`/data/options.json`) or a standalone JSON config.
    *   **Discovery:** Supports Home Assistant MQTT Discovery for automatic entity creation.

## Key Files & Structure

*   `ezville_wallpad/`
    *   `ezville_wallpad.py`: The main application script. Contains protocol definitions (`RS485_DEVICE`) and the main loop.
    *   `Dockerfile`: Defines the container environment (Python 3.10 base).
    *   `config.json`: Home Assistant Add-on configuration schema.
    *   `run_addon.sh`: Entry point script for the Add-on environment.
    *   `run_standalone.sh`: Helper script to run the addon locally without Home Assistant Supervisor.
    *   `generate_options_standalone.py`: Generates a default `options_standalone.json` for standalone usage.
    *   `DOCS_PACKETS.md`: (Reference) Documentation on the RS485 packet structure.

## Building and Running

### As Home Assistant Add-on
This project is intended to be installed as a local Add-on in Home Assistant.
1.  Navigate to the Add-on Store in Home Assistant.
2.  Add the local repository or the URL of this repository.
3.  Install "EzVille RS485 Addon".
4.  Configure the `serial_mode` (Serial or Socket) and MQTT settings in the "Configuration" tab.
5.  Start the Add-on.

### Standalone (Local Development)
You can run the script directly on your machine for testing or if you are not using HAOS.

**Prerequisites:**
*   Python 3.10+
*   `pip install pyserial paho-mqtt`

**Execution:**
1.  Navigate to the `ezville_wallpad` directory.
2.  Run `./run_standalone.sh`.
3.  On the first run, it will generate `options_standalone.json`.
4.  Edit `options_standalone.json` with your MQTT broker details and Serial/Socket connection info.
5.  Run `./run_standalone.sh` again to start the application.

### Docker (Manual Build)
To build and run the container manually:

```bash
cd ezville_wallpad
docker build -t ezville_wallpad .
docker run -it --rm -v $(pwd):/share ezville_wallpad
```
*(Note: You may need to map serial devices or provide network access depending on your connection mode.)*

## Development Conventions

*   **Language:** Python.
*   **Style:** Follows general Python guidelines. Logic is contained in a single large script (`ezville_wallpad.py`) with global dictionary constants defining the protocol.
*   **Protocol Handling:**
    *   Packets are hex-encoded.
    *   `RS485_DEVICE` dictionary maps device types (light, thermostat) to their command codes.
    *   `DISCOVERY_PAYLOAD` defines the MQTT discovery config for Home Assistant.
