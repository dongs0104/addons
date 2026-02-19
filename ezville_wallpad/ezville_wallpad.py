# first written by nandflash("저장장치") <github@printk.info> since 2020-06-25
# Second Modify by KT("ktdo79") <ktdo79@gmail.com> since 2022-06-25

# This is a part of EzVille Wallpad Addon for Home Assistant
# Author: Dong SHIN <d0104.shin@gmail.com> 2026-01-22
# Refactored to MQTT-only structure: 2025-01-25

import paho.mqtt.client as paho_mqtt
import json
import sys
import time
import datetime
import logging
from logging.handlers import TimedRotatingFileHandler
import os.path
import re
import threading

RS485_DEVICE = {
    "light": {
        "query": {
            "id": 0x0E,
            "cmd": 0x01,
        },
        "state": {
            "id": 0x0E,
            "cmd": 0x81,
        },
        "last": {},
        "power": {
            "id": 0x0E,
            "cmd": 0x41,
            "ack": 0xC1,
        },
    },
    "thermostat": {
        "query": {
            "id": 0x36,
            "cmd": 0x01,
        },
        "state": {
            "id": 0x36,
            "cmd": 0x81,
        },
        "last": {},
        "away": {
            "id": 0x36,
            "cmd": 0x45,
            "ack": 0x00,
        },
        "target": {
            "id": 0x36,
            "cmd": 0x44,
            "ack": 0xC4,
        },
    },
    "gasvalve": {
        "state": {"id": 0x12, "cmd": 0x81},
        "power": {"id": 0x12, "cmd": 0x41, "ack": 0xC1},
    },
    "batch": {
        "state": {"id": 0x33, "cmd": 0x81},
        "press": {"id": 0x33, "cmd": 0x41, "ack": 0xC1},
    },
    "plug": {
        "state": {"id": 0x50, "cmd": 0x81},
        "power": {"id": 0x50, "cmd": 0x43, "ack": 0xC3},
    },
}

DISCOVERY_DEVICE = {
    "ids": [
        "ezville_wallpad",
    ],
    "name": "ezville_wallpad",
    "mf": "EzVille",
    "mdl": "EzVille Wallpad",
    "sw": "dongs0104/ha_addons/ezville_wallpad",
}

DISCOVERY_PAYLOAD = {
    "light": [
        {
            "_intg": "light",
            "~": "{prefix}/light/{grp}_{rm}_{id}",
            "name": "{prefix}_light_{grp}_{rm}_{id}",
            "opt": True,
            "stat_t": "~/power/state",
            "cmd_t": "~/power/command",
        }
    ],
    "thermostat": [
        {
            "_intg": "climate",
            "~": "{prefix}/thermostat/{grp}_{id}",
            "name": "{prefix}_thermostat_{grp}_{id}",
            "mode_stat_t": "~/power/state",
            "temp_stat_t": "~/target/state",
            "temp_cmd_t": "~/target/command",
            "curr_temp_t": "~/current/state",
            "away_stat_t": "~/away/state",
            "away_cmd_t": "~/away/command",
            "modes": ["off", "heat"],
            "min_temp": 5,
            "max_temp": 40,
        }
    ],
    "plug": [
        {
            "_intg": "switch",
            "~": "{prefix}/plug/{idn}/power",
            "name": "{prefix}_plug_{idn}",
            "stat_t": "~/state",
            "cmd_t": "~/command",
            "icon": "mdi:power-plug",
        },
        {
            "_intg": "switch",
            "~": "{prefix}/plug/{idn}/idlecut",
            "name": "{prefix}_plug_{idn}_standby_cutoff",
            "stat_t": "~/state",
            "cmd_t": "~/command",
            "icon": "mdi:leaf",
        },
        {
            "_intg": "sensor",
            "~": "{prefix}/plug/{idn}",
            "name": "{prefix}_plug_{idn}_power_usage",
            "stat_t": "~/current/state",
            "unit_of_meas": "W",
        },
    ],
    "cutoff": [
        {
            "_intg": "switch",
            "~": "{prefix}/cutoff/{idn}/power",
            "name": "{prefix}_light_cutoff_{idn}",
            "stat_t": "~/state",
            "cmd_t": "~/command",
        }
    ],
    "gasvalve": [
        {
            "_intg": "switch",
            "~": "{prefix}/gasvalve/{idn}",
            "name": "{prefix}_gasvalve_{idn}",
            "stat_t": "~/power/state",
            "cmd_t": "~/power/command",
            "icon": "mdi:valve",
        }
    ],
    "energy": [
        {
            "_intg": "sensor",
            "~": "{prefix}/energy/{idn}",
            "name": "_",
            "stat_t": "~/current/state",
            "unit_of_meas": "_",
            "val_tpl": "_",
        }
    ],
}

STATE_HEADER = {
    prop["state"]["id"]: (device, prop["state"]["cmd"])
    for device, prop in RS485_DEVICE.items()
    if "state" in prop
}
QUERY_HEADER = {
    prop["query"]["id"]: (device, prop["query"]["cmd"])
    for device, prop in RS485_DEVICE.items()
    if "query" in prop
}
ACK_HEADER = {
    prop[cmd]["id"]: (device, prop[cmd]["ack"])
    for device, prop in RS485_DEVICE.items()
    for cmd, code in prop.items()
    if "ack" in code
}

ACK_MAP = {}
for device, prop in RS485_DEVICE.items():
    for cmd, code in prop.items():
        if "ack" in code:
            if code["id"] not in ACK_MAP:
                ACK_MAP[code["id"]] = {}
            ACK_MAP[code["id"]][code["cmd"]] = code["ack"]

# 전역 변수
serial_queue = {}
serial_ack = {}
last_topic_list = {}

mqtt = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
mqtt_connected = False

logger = logging.getLogger(__name__)

# Watchdog 관련 전역 변수
last_packet_time = time.time()

# 패킷 버퍼 (MQTT에서 받은 RS485 데이터 처리용)
packet_buffer = bytearray()
packet_buffer_lock = threading.Lock()

# 명령 전송 관련
command_send_lock = threading.Lock()
last_command_time = 0


class PacketBuffer:
    """RS485 패킷 버퍼 관리 클래스"""

    def __init__(self):
        self._buffer = bytearray()
        self._lock = threading.Lock()

    def add_data(self, data: bytes):
        """버퍼에 데이터 추가"""
        with self._lock:
            self._buffer.extend(data)

    def get_packet(self):
        """
        버퍼에서 완전한 패킷 하나를 추출
        패킷 구조: [0xF7][device_id][room_id][cmd][length][data...][XOR][ADD]
        """
        with self._lock:
            # 0xF7 시작점 찾기
            while len(self._buffer) > 0 and self._buffer[0] != 0xF7:
                del self._buffer[0]

            # 최소 패킷 길이 확인 (헤더 5바이트 + 체크섬 2바이트)
            if len(self._buffer) < 7:
                return None

            # 패킷 길이 확인 (4번째 바이트가 데이터 길이)
            data_length = self._buffer[4]
            packet_length = 5 + data_length + 2  # 헤더(5) + 데이터 + 체크섬(2)

            if len(self._buffer) < packet_length:
                return None

            # 패킷 추출
            packet = bytes(self._buffer[:packet_length])
            del self._buffer[:packet_length]

            return packet

    def clear(self):
        """버퍼 초기화"""
        with self._lock:
            self._buffer.clear()


# 패킷 버퍼 인스턴스
packet_buffer = PacketBuffer()


def init_logger():
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S"
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def init_logger_file():
    if Options["log"]["to_file"]:
        filename = Options["log"]["filename"]
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler = TimedRotatingFileHandler(
            os.path.abspath(Options["log"]["filename"]), when="midnight", backupCount=7
        )
        handler.setFormatter(formatter)
        handler.suffix = "%Y%m%d"
        logger.addHandler(handler)


def init_option(argv):
    if len(argv) == 1:
        option_file = "./options_standalone.json"
    else:
        option_file = argv[1]

    global Options

    default_file = os.path.join(
        os.path.dirname(os.path.abspath(argv[0])), "config.json"
    )

    with open(default_file, encoding="utf-8") as f:
        config = json.load(f)
        logger.info("addon version %s", config["version"])
        Options = config["options"]
    with open(option_file, encoding="utf-8") as f:
        Options2 = json.load(f)

    for k, v in Options.items():
        if isinstance(v, dict) and k in Options2:
            Options[k].update(Options2[k])
            for k2 in Options[k].keys():
                if k2 not in Options2[k].keys():
                    logger.warning(
                        "no configuration value for '%s:%s'! try default value (%s)...",
                        k,
                        k2,
                        Options[k][k2],
                    )
        else:
            if k not in Options2:
                logger.warning(
                    "no configuration value for '%s'! try default value (%s)...",
                    k,
                    Options[k],
                )
            else:
                Options[k] = Options2[k]

    Options["mqtt"]["server"] = re.sub("[a-z]*://", "", Options["mqtt"]["server"])
    if Options["mqtt"]["server"] == "127.0.0.1":
        logger.warning("MQTT server address should be changed!")

    Options["mqtt"]["_discovery"] = Options["mqtt"]["discovery"]


def serial_verify_checksum(packet):
    """패킷 체크섬 검증"""
    if len(packet) < 7:
        return False

    # XOR 체크섬 (마지막 ADD 바이트 제외)
    checksum = 0
    for b in packet[:-1]:
        checksum ^= b

    # ADD 계산
    add = sum(packet[:-1]) & 0xFF

    if checksum != 0 or add != packet[-1]:
        logger.warning(
            "checksum fail! {}, xor:{:02x}, add:{:02x}".format(
                packet.hex(), checksum, add
            )
        )
        return False

    return True


def serial_generate_checksum(packet):
    """패킷 체크섬 생성"""
    checksum = 0
    for b in packet[:-1]:
        checksum ^= b

    add = (sum(packet) + checksum) & 0xFF

    return checksum, add


def rs485_send(packet: bytes):
    """RS485로 패킷 전송 (MQTT를 통해)"""
    global last_command_time

    if not mqtt_connected:
        logger.warning("MQTT not connected, cannot send RS485 packet")
        return False

    send_topic = Options["rs485_mqtt"]["send_topic"]

    with command_send_lock:
        # 명령 간 최소 간격 유지 (100ms)
        elapsed = time.time() - last_command_time
        if elapsed < 0.1:
            time.sleep(0.1 - elapsed)

        mqtt.publish(send_topic, packet)
        last_command_time = time.time()
        logger.info("send to RS485:   {}".format(packet.hex()))

    return True


def mqtt_discovery(payload):
    """MQTT Discovery 메시지 발행"""
    intg = payload.pop("_intg")

    payload["device"] = DISCOVERY_DEVICE
    payload["uniq_id"] = payload["name"]

    topic = f"homeassistant/{intg}/ezville_wallpad/{payload['name']}/config"
    logger.info("Add new device: %s", topic)
    mqtt.publish(topic, json.dumps(payload))


def mqtt_debug(topics, payload):
    """디버그 명령 처리"""
    device = topics[2]
    command = topics[3]

    if device == "packet":
        if command == "send":
            packet = bytearray.fromhex(payload)
            packet[-2], packet[-1] = serial_generate_checksum(packet)
            packet = bytes(packet)

            logger.info("prepare packet:  {}".format(packet.hex()))
            serial_queue[packet] = time.time()


def mqtt_device(topics, payload):
    """HA에서 받은 장치 제어 명령 처리"""
    device = topics[1]
    idn = topics[2]
    cmd = topics[3]

    if device not in RS485_DEVICE:
        logger.error("    unknown device!")
        return
    if cmd not in RS485_DEVICE[device]:
        logger.error("    unknown command!")
        return
    if payload == "":
        logger.error("    no payload!")
        return

    cmd = RS485_DEVICE[device][cmd]
    packet = None

    if device == "light":
        if payload == "ON":
            payload = 0xF1 if idn.startswith("1_1") else 0x01
        elif payload == "OFF":
            payload = 0x00
        length = 10
        packet = bytearray(length)
        packet[0] = 0xF7
        packet[1] = cmd["id"]
        packet[2] = int(idn.split("_")[0]) << 4 | int(idn.split("_")[1])
        packet[3] = cmd["cmd"]
        packet[4] = 0x03
        packet[5] = int(idn.split("_")[2])
        packet[6] = payload
        packet[7] = 0x00
        packet[8], packet[9] = serial_generate_checksum(packet)

    elif device == "thermostat":
        if payload == "heat":
            payload = 0x01
        elif payload == "off":
            payload = 0x00
        length = 8
        packet = bytearray(length)
        packet[0] = 0xF7
        packet[1] = cmd["id"]
        packet[2] = int(idn.split("_")[0]) << 4 | int(idn.split("_")[1])
        packet[3] = cmd["cmd"]
        packet[4] = 0x01
        packet[5] = int(float(payload))
        packet[6], packet[7] = serial_generate_checksum(packet)

    elif device == "gasvalve":
        if payload == "off":
            payload = 0x00
            length = 8
            packet = bytearray(length)
            packet[0] = 0xF7
            packet[1] = cmd["id"]
            packet[2] = int(idn) if idn.isdigit() else 0x01
            packet[3] = cmd["cmd"]
            packet[4] = 0x01
            packet[5] = int(float(payload))
            packet[6], packet[7] = serial_generate_checksum(packet)

    if packet:
        packet = bytes(packet)
        serial_queue[packet] = time.time()


def mqtt_init_discovery():
    """Discovery 초기화"""
    Options["mqtt"]["_discovery"] = Options["mqtt"]["discovery"]
    for device in RS485_DEVICE:
        RS485_DEVICE[device]["last"] = {}

    global last_topic_list
    last_topic_list = {}


def serial_new_device(device, packet, idn=None):
    """새 장치 Discovery 등록"""
    prefix = Options["mqtt"]["prefix"]

    if device == "light":
        grp_id = int(packet[2] >> 4)
        rm_id = int(packet[2] & 0x0F)
        light_count = int(packet[4]) - 1

        for light_id in range(1, light_count + 1):
            payload = DISCOVERY_PAYLOAD[device][0].copy()
            payload["~"] = payload["~"].format(
                prefix=prefix, grp=grp_id, rm=rm_id, id=light_id
            )
            payload["name"] = payload["name"].format(
                prefix=prefix, grp=grp_id, rm=rm_id, id=light_id
            )
            mqtt_discovery(payload)

    elif device == "thermostat":
        grp_id = int(packet[2] >> 4)
        room_count = int((int(packet[4]) - 5) / 2)

        for room_id in range(1, room_count + 1):
            payload = DISCOVERY_PAYLOAD[device][0].copy()
            payload["~"] = payload["~"].format(prefix=prefix, grp=grp_id, id=room_id)
            payload["name"] = payload["name"].format(
                prefix=prefix, grp=grp_id, id=room_id
            )
            mqtt_discovery(payload)

    elif device in DISCOVERY_PAYLOAD:
        for payloads in DISCOVERY_PAYLOAD[device]:
            payload = payloads.copy()

            payload["~"] = payload["~"].format(prefix=prefix, idn=idn)
            payload["name"] = payload["name"].format(prefix=prefix, idn=idn)

            if device == "energy":
                payload["name"] = "{}_{}_consumption".format(
                    prefix, ("power", "gas", "water")[idn]
                )
                payload["unit_of_meas"] = ("W", "m³/h", "m³/h")[idn]
                payload["val_tpl"] = (
                    "{{ value }}",
                    "{{ value | float / 100 }}",
                    "{{ value | float / 100 }}",
                )[idn]

            mqtt_discovery(payload)


def serial_receive_state(device, packet):
    """장치 상태 수신 및 HA로 발행"""
    last = RS485_DEVICE[device]["last"]
    idn = (packet[1] << 8) | packet[2]

    if last.get(idn) == packet:
        return

    if Options["mqtt"]["_discovery"] and not last.get(idn):
        serial_new_device(device, packet, idn)
        last[idn] = True
        return
    else:
        last[idn] = packet

    prefix = Options["mqtt"]["prefix"]

    if device == "light":
        grp_id = int(packet[2] >> 4)
        rm_id = int(packet[2] & 0x0F)
        light_count = int(packet[4]) - 1

        for light_id in range(1, light_count + 1):
            topic = f"{prefix}/{device}/{grp_id}_{rm_id}_{light_id}/power/state"
            value = "ON" if packet[5 + light_id] & 1 else "OFF"

            if last_topic_list.get(topic) != value:
                logger.info(
                    "publish to HA:   %s = %s (%s)", topic, value, packet.hex()
                )
                mqtt.publish(topic, value)
                last_topic_list[topic] = value

    elif device == "thermostat":
        grp_id = int(packet[2] >> 4)
        room_count = int((int(packet[4]) - 5) / 2)

        for thermostat_id in range(1, room_count + 1):
            # 수정: id 대신 thermostat_id 사용
            power_bit = (packet[6] & 0x1F) >> (room_count - thermostat_id)
            away_bit = (packet[7] & 0x1F) >> (room_count - thermostat_id)

            value1 = "ON" if power_bit & 1 else "OFF"
            value2 = "ON" if away_bit & 1 else "OFF"
            value3 = packet[8 + thermostat_id * 2]
            value4 = packet[9 + thermostat_id * 2]

            for sub_topic, value in zip(
                ["power", "away", "target", "current"], [value1, value2, value3, value4]
            ):
                topic = f"{prefix}/{device}/{grp_id}_{thermostat_id}/{sub_topic}/state"
                if last_topic_list.get(topic) != value:
                    logger.info(
                        "publish to HA:   %s = %s (%s)", topic, value, packet.hex()
                    )
                    mqtt.publish(topic, value)
                    last_topic_list[topic] = value


def serial_ack_command(header):
    """ACK 수신 처리"""
    if header in serial_ack:
        logger.info(
            "ack from device: {} ({:x})".format(serial_ack[header].hex(), header)
        )
        serial_queue.pop(serial_ack[header], None)
        serial_ack.pop(header)


def process_single_packet(packet):
    """단일 패킷 처리"""
    global last_packet_time

    if len(packet) < 7:
        return

    if not serial_verify_checksum(packet):
        return

    last_packet_time = time.time()

    header_1 = packet[1]  # device id
    header_3 = packet[3]  # command

    # 상태 응답 처리
    if header_1 in STATE_HEADER and header_3 == STATE_HEADER[header_1][1]:
        device = STATE_HEADER[header_1][0]
        serial_receive_state(device, packet)

        # 대기 중인 명령이 있으면 전송
        if serial_queue:
            send_pending_command()

    # ACK 처리
    elif header_1 in ACK_HEADER:
        header = (
            packet[0] << 24 | packet[1] << 16 | packet[2] << 8 | packet[3]
        )
        serial_ack_command(header)

    # 명령 전송 타이밍 (상태 응답 이후)
    # 수정: 항상 True였던 조건문 수정
    elif header_3 in (0x81, 0x8F, 0x0F):
        if serial_queue:
            send_pending_command()


def send_pending_command():
    """대기 중인 명령 전송"""
    if not serial_queue:
        return

    cmd = next(iter(serial_queue))

    # ACK 헤더 생성
    if cmd[1] in ACK_MAP and cmd[3] in ACK_MAP[cmd[1]]:
        ack = bytearray(cmd[0:4])
        ack[3] = ACK_MAP[cmd[1]][cmd[3]]
        waive_ack = ack[3] == 0x00
        ack_int = int.from_bytes(ack, "big")

        elapsed = time.time() - serial_queue[cmd]

        if elapsed > Options["rs485"]["max_retry"]:
            logger.error(
                "send to device:  {} max retry time exceeded!".format(cmd.hex())
            )
            serial_queue.pop(cmd)
            serial_ack.pop(ack_int, None)
        elif waive_ack:
            rs485_send(cmd)
            logger.info("waive ack:  {}".format(cmd.hex()))
            serial_queue.pop(cmd)
        elif elapsed > 3:
            rs485_send(cmd)
            logger.warning(
                "send to device:  {}, try another {:.01f} seconds...".format(
                    cmd.hex(), Options["rs485"]["max_retry"] - elapsed
                )
            )
            serial_ack[ack_int] = cmd
        else:
            rs485_send(cmd)
            serial_ack[ack_int] = cmd
    else:
        # ACK 맵에 없는 경우 그냥 전송
        rs485_send(cmd)
        serial_queue.pop(cmd)


def process_packets():
    """버퍼에서 패킷 추출 및 처리"""
    while True:
        packet = packet_buffer.get_packet()
        if packet is None:
            break
        process_single_packet(packet)


def mqtt_on_rs485_recv(msg):
    """EW11에서 RS485 데이터 수신"""
    packet_buffer.add_data(msg.payload)
    process_packets()


def mqtt_on_message(client, userdata, msg):
    """MQTT 메시지 수신 콜백"""
    topic = msg.topic
    recv_topic = Options["rs485_mqtt"]["recv_topic"]

    # EW11에서 RS485 데이터 수신
    if topic == recv_topic:
        mqtt_on_rs485_recv(msg)
        return

    # 기존 처리
    topics = topic.split("/")

    if len(topics) < 2:
        return

    try:
        payload = msg.payload.decode()
    except:
        return

    logger.info("recv. from HA:   %s = %s", topic, payload)

    device = topics[1]
    if device == "status":
        if payload == "online":
            mqtt_init_discovery()
    elif device == "debug":
        mqtt_debug(topics, payload)
    elif len(topics) >= 4:
        mqtt_device(topics, payload)


def mqtt_on_connect(client, userdata, flags, rc, properties):
    """MQTT 연결 콜백"""
    if rc == 0:
        logger.info("MQTT connect successful!")
        global mqtt_connected
        mqtt_connected = True
    else:
        logger.error("MQTT connection return with:  %s", paho_mqtt.connack_string(rc))

    mqtt_init_discovery()

    # RS485 수신 토픽 구독
    recv_topic = Options["rs485_mqtt"]["recv_topic"]
    logger.info("subscribe %s", recv_topic)
    mqtt.subscribe(recv_topic, 0)

    # HA 상태 토픽 구독
    topic = "homeassistant/status"
    logger.info("subscribe %s", topic)
    mqtt.subscribe(topic, 0)

    # 장치 제어 명령 토픽 구독
    prefix = Options["mqtt"]["prefix"]
    if Options["wallpad_mode"] != "off":
        topic = f"{prefix}/+/+/+/command"
        logger.info("subscribe %s", topic)
        mqtt.subscribe(topic, 0)


def mqtt_on_disconnect(client, userdata, rc):
    """MQTT 연결 해제 콜백"""
    logger.warning("MQTT disconnected! (%s)", rc)
    global mqtt_connected
    mqtt_connected = False


def start_mqtt_loop():
    """MQTT 루프 시작"""
    logger.info("initialize mqtt...")

    mqtt.on_message = mqtt_on_message
    mqtt.on_connect = mqtt_on_connect
    mqtt.on_disconnect = mqtt_on_disconnect

    if Options["mqtt"]["need_login"]:
        mqtt.username_pw_set(Options["mqtt"]["user"], Options["mqtt"]["passwd"])

    try:
        mqtt.connect(Options["mqtt"]["server"], Options["mqtt"]["port"])
    except Exception as e:
        logger.error("MQTT server address/port may be incorrect! (%s)", e)
        sys.exit(1)

    mqtt.loop_start()

    delay = 1
    while not mqtt_connected:
        logger.info("waiting MQTT connected ...")
        time.sleep(delay)
        delay = min(delay * 2, 10)


def watchdog_loop():
    """Watchdog 루프 - 패킷 수신 모니터링 및 자동 재시작"""
    global last_packet_time

    timeout = Options.get("watchdog", {}).get("timeout", 60)
    restart_time = Options.get("restart", {}).get("time", "")
    inactivity_min = Options.get("restart", {}).get("inactivity", 0)

    if timeout <= 0 and not restart_time and inactivity_min <= 0:
        logger.info("Watchdog and restart disabled")
        return

    logger.info(
        "Watchdog started (timeout: %ds, restart_time: %s, inactivity: %d min)",
        timeout,
        restart_time or "disabled",
        inactivity_min,
    )

    while True:
        time.sleep(10)

        # 스케줄 재시작: 매일 지정 시각에 프로세스 재시작
        if restart_time:
            now_hm = datetime.datetime.now().strftime("%H:%M")
            if now_hm == restart_time:
                logger.info("Scheduled restart at %s", restart_time)
                sys.exit(0)

        # 비활성 재시작: N분간 패킷 수신 없으면 프로세스 재시작
        if inactivity_min > 0:
            inactivity_sec = inactivity_min * 60
            elapsed = time.time() - last_packet_time
            if elapsed > inactivity_sec:
                logger.warning(
                    "No packets for %.0f seconds (limit: %d min). Restarting...",
                    elapsed,
                    inactivity_min,
                )
                sys.exit(0)

        # Watchdog 경고: timeout 초과 시 경고 로그 및 버퍼 초기화
        if timeout > 0:
            elapsed = time.time() - last_packet_time
            if elapsed > timeout:
                logger.warning(
                    "No packet received for %.1f seconds (timeout: %d)",
                    elapsed,
                    timeout,
                )
                packet_buffer.clear()

        # 오래된 명령 정리
        current_time = time.time()
        expired_cmds = [
            cmd
            for cmd, timestamp in serial_queue.items()
            if current_time - timestamp > Options["rs485"]["max_retry"]
        ]
        for cmd in expired_cmds:
            logger.warning("Expired command removed: %s", cmd.hex())
            serial_queue.pop(cmd, None)


if __name__ == "__main__":
    init_logger()
    init_option(sys.argv)
    init_logger_file()

    logger.info("Starting EzVille Wallpad Addon (MQTT-only mode)")

    start_mqtt_loop()

    # Watchdog 스레드 시작
    watchdog_thread = threading.Thread(target=watchdog_loop, daemon=True)
    watchdog_thread.start()

    logger.info("Addon running. Waiting for RS485 packets via MQTT...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Addon stopped by user")
    except Exception as e:
        logger.exception("Addon finished with error: %s", e)
