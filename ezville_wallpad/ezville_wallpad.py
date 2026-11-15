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
        "state": {"id": 0x0E, "cmd": 0x81},
        "last": {},
        "power": {"id": 0x0E, "cmd": 0x41, "ack": 0xC1},
    },
    "thermostat": {
        "state": {"id": 0x36, "cmd": 0x81},
        "last": {},
        "power": {"id": 0x36, "cmd": 0x43, "ack": 0xC3},
        "away": {"id": 0x36, "cmd": 0x45, "ack": 0x00},  # 응답 없음
        "target": {"id": 0x36, "cmd": 0x44, "ack": 0xC4},
    },
}

DISCOVERY_DEVICE = {
    "ids": ["ezville_wallpad"],
    "name": "ezville_wallpad",
    "mf": "EzVille",
    "mdl": "EzVille Wallpad",
    "sw": "dongs0104/ha_addons/ezville_wallpad",
}

DISCOVERY_PAYLOAD = {
    "light": {
        "_intg": "light",
        "~": "{prefix}/light/{grp}_{rm}_{id}",
        "name": "{prefix}_light_{grp}_{rm}_{id}",
        "opt": True,
        "stat_t": "~/power/state",
        "cmd_t": "~/power/command",
    },
    # 디밍 조명에만 추가되는 키
    "light_dimming": {
        "bri_stat_t": "~/brightness/state",
        "bri_cmd_t": "~/brightness/command",
        "bri_scl": 4,  # 실측: 4단계, 명령 = 단계<<4 | 1
        "on_cmd_type": "brightness",  # 켤 때 ON 대신 밝기만 전송 (이중 전송 방지)
    },
    "thermostat": {
        "_intg": "climate",
        "~": "{prefix}/thermostat/{grp}_{id}",
        "name": "{prefix}_thermostat_{grp}_{id}",
        "mode_stat_t": "~/power/state",
        "mode_cmd_t": "~/power/command",
        "temp_stat_t": "~/target/state",
        "temp_cmd_t": "~/target/command",
        "curr_temp_t": "~/current/state",
        "modes": ["off", "heat"],
        "min_temp": 5,
        "max_temp": 40,
    },
}

STATE_HEADER = {
    prop["state"]["id"]: (device, prop["state"]["cmd"])
    for device, prop in RS485_DEVICE.items()
}

ACK_MAP = {}
for device, prop in RS485_DEVICE.items():
    for cmd, code in prop.items():
        if "ack" in code:
            ACK_MAP.setdefault(code["id"], {})[code["cmd"]] = code["ack"]
ACK_HEADER = ACK_MAP.keys()

# 전역 변수
serial_queue = {}
serial_ack = {}
last_topic_list = {}

mqtt = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
mqtt_connected = False

logger = logging.getLogger(__name__)

# Watchdog 관련 전역 변수
last_packet_time = time.time()

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


def make_packet(dev_id, room, cmd, data):
    """[F7][dev_id][room][cmd][len][data...][XOR][ADD] 패킷 생성"""
    packet = bytearray([0xF7, dev_id, room, cmd, len(data), *data, 0, 0])
    packet[-2], packet[-1] = serial_generate_checksum(packet)
    return bytes(packet)


def encode_temp(value):
    """온도 → 바이트 (BIT7: 0.5도)"""
    t = float(value)
    return int(t) | (0x80 if t % 1 >= 0.5 else 0)


def decode_temp(byte):
    t = (byte & 0x7F) + (0.5 if byte & 0x80 else 0)
    return int(t) if t.is_integer() else t


def is_dimming(idn):
    return idn in Options.get("light_dimming", [])


def mqtt_device(topics, payload):
    """HA에서 받은 장치 제어 명령 처리"""
    device, idn, sub = topics[1], topics[2], topics[3]

    if device not in RS485_DEVICE:
        logger.error("    unknown device!")
        return
    if payload == "":
        logger.error("    no payload!")
        return

    ids = [int(x) for x in idn.split("_")]
    room = ids[0] << 4 | ids[1]
    packet = None

    if device == "light" and sub in ("power", "brightness"):
        if sub == "brightness":
            level = max(0, min(4, int(float(payload))))
            value = level << 4 | 1 if level else 0x00
        else:
            value = 0x01 if payload == "ON" else 0x00
        cmd = RS485_DEVICE["light"]["power"]
        packet = make_packet(cmd["id"], room, cmd["cmd"], [ids[2], value, 0x00])

    elif device == "thermostat" and sub == "power":
        # off는 외출 모드로 매핑 (월패드 난방 끄기 = 외출)
        cmd = RS485_DEVICE["thermostat"]["power" if payload == "heat" else "away"]
        packet = make_packet(cmd["id"], room, cmd["cmd"], [0x01])

    elif device == "thermostat" and sub == "target":
        cmd = RS485_DEVICE["thermostat"]["target"]
        packet = make_packet(cmd["id"], room, cmd["cmd"], [encode_temp(payload)])

    if packet:
        serial_queue[packet] = time.time()
    else:
        logger.error("    unknown command!")


def mqtt_init_discovery():
    """Discovery 초기화"""
    Options["mqtt"]["_discovery"] = Options["mqtt"]["discovery"]
    for device in RS485_DEVICE:
        RS485_DEVICE[device]["last"] = {}

    global last_topic_list
    last_topic_list = {}


def serial_new_device(device, packet):
    """새 장치 Discovery 등록"""
    prefix = Options["mqtt"]["prefix"]
    grp_id = packet[2] >> 4

    if device == "light":
        rm_id = packet[2] & 0x0F
        for light_id in range(1, packet[4]):
            idn = f"{grp_id}_{rm_id}_{light_id}"
            payload = DISCOVERY_PAYLOAD["light"].copy()
            payload["~"] = f"{prefix}/light/{idn}"
            payload["name"] = f"{prefix}_light_{idn}"
            if is_dimming(idn):
                payload.update(DISCOVERY_PAYLOAD["light_dimming"])
            mqtt_discovery(payload)

    elif device == "thermostat":
        for room_id in range(1, (packet[4] - 5) // 2 + 1):
            payload = DISCOVERY_PAYLOAD["thermostat"].copy()
            payload["~"] = f"{prefix}/thermostat/{grp_id}_{room_id}"
            payload["name"] = f"{prefix}_thermostat_{grp_id}_{room_id}"
            mqtt_discovery(payload)


def publish_state(topic, value, packet):
    if last_topic_list.get(topic) != value:
        logger.info("publish to HA:   %s = %s (%s)", topic, value, packet.hex())
        mqtt.publish(topic, value)
        last_topic_list[topic] = value


def serial_receive_state(device, packet):
    """장치 상태 수신 및 HA로 발행"""
    last = RS485_DEVICE[device]["last"]
    idn = (packet[1] << 8) | packet[2]

    if last.get(idn) == packet:
        return

    if Options["mqtt"]["_discovery"] and not last.get(idn):
        serial_new_device(device, packet)
        last[idn] = True
        return
    last[idn] = packet

    prefix = Options["mqtt"]["prefix"]
    grp_id = packet[2] >> 4

    if device == "light":
        rm_id = packet[2] & 0x0F
        for light_id in range(1, packet[4]):
            light = f"{grp_id}_{rm_id}_{light_id}"
            value = packet[5 + light_id]
            publish_state(
                f"{prefix}/light/{light}/power/state",
                "ON" if value & 1 else "OFF",
                packet,
            )
            if is_dimming(light) and value & 1 and value >> 4:
                publish_state(
                    f"{prefix}/light/{light}/brightness/state", value >> 4, packet
                )

    elif device == "thermostat":
        room_count = (packet[4] - 5) // 2
        for room_id in range(1, room_count + 1):
            # ponytail: 1번 방 = 상위 비트 가정 (simple_mqtt는 BIT0 가정), 실측 필요
            power_bit = (packet[6] & 0x1F) >> (room_count - room_id) & 1
            base = f"{prefix}/thermostat/{grp_id}_{room_id}"
            publish_state(f"{base}/power/state", "heat" if power_bit else "off", packet)
            publish_state(
                f"{base}/target/state", decode_temp(packet[8 + room_id * 2]), packet
            )
            publish_state(
                f"{base}/current/state", decode_temp(packet[9 + room_id * 2]), packet
            )


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
        serial_ack_command(int.from_bytes(packet[:4], "big"))

    # 명령 전송 타이밍 (상태 응답 이후)
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
    except UnicodeDecodeError:
        return

    logger.info("recv. from HA:   %s = %s", topic, payload)

    device = topics[1]
    if device == "status":
        if payload == "online":
            mqtt_init_discovery()
    elif device == "debug":
        mqtt_debug(topics, payload)
    elif len(topics) >= 4:
        try:
            mqtt_device(topics, payload)
        except (ValueError, IndexError) as e:
            logger.error("    invalid command %s = %s (%s)", topic, payload, e)


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
