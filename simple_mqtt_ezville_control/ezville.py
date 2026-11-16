"""이지빌 월패드 ↔ Home Assistant (MQTT Discovery) 브리지

EW11은 MQTT 모드로 연결: 수신 ew11/recv, 송신 ew11/send
"""

import asyncio
import json
import random
import sys
import time

import paho.mqtt.client as mqtt

import packet as pk
from devices import BY_NAME, DEVICES, Command, entity

HA_TOPIC = "ezville"
EW11_TOPIC = "ew11"
HA_STATUS_TOPIC = "homeassistant/status"
OPTIONS_FILE = "/data/options.json"

DISCOVERY_DEVICE = {
    "ids": ["ezville_wallpad"],
    "name": "ezville_wallpad",  # 엔티티 ID 접두어, 바꾸지 말 것
    "mf": "EzVille",
    "mdl": "EzVille Wallpad",
    "sw": "dongs0104/addons/ezville_wallpad",
}


def log(msg):
    print(time.strftime("[%Y-%m-%d %p %I:%M:%S] ") + msg, flush=True)


class Wallpad:
    def __init__(self, cfg):
        self.cfg = cfg
        self.debug = cfg["DEBUG_LOG"]
        self.mqtt_log = cfg["MQTT_LOG"]
        self.ew11_log = cfg["EW11_LOG"]

        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "mqtt-ezville")
        self.mqtt.username_pw_set(cfg["mqtt_id"], cfg["mqtt_password"])
        self.mqtt.on_connect = self.on_connect
        self.mqtt.on_message = self.on_message
        self.mqtt.on_disconnect = lambda *a: log("[INFO] MQTT 연결 해제")

        self.ha_online = asyncio.Event()
        self.ha_offline = asyncio.Event()
        self.startup_delay = 0
        self.reset()

    def reset(self):
        self.inbox = asyncio.Queue()  # (topic, payload) MQTT 수신
        self.commands = asyncio.Queue()
        self.state = {}  # "light_01_01power" -> "ON"
        self.discovered = set()
        self.residue = b""
        self.force_update = False
        self.last_received = time.time()

    # ---------- MQTT ----------
    def on_connect(self, client, userdata, flags, rc, properties):
        if rc != 0:
            log("[ERROR] MQTT 연결 실패: {}".format(rc))
            return
        log("[INFO] MQTT Broker 연결 성공")
        topics = [HA_TOPIC + "/+/+/command", HA_STATUS_TOPIC, EW11_TOPIC + "/recv"]
        client.subscribe([(t, 0) for t in topics])

    def on_message(self, client, userdata, msg):
        # paho 스레드 → asyncio 루프로 넘김
        self.loop.call_soon_threadsafe(
            self.dispatch, msg.topic, msg.payload, msg.retain
        )

    def dispatch(self, topic, payload, retain):
        if topic != HA_STATUS_TOPIC:
            self.inbox.put_nowait((topic, payload))
        elif self.cfg["reboot_control"]:
            if payload == b"online":
                log("[INFO] MQTT Integration 온라인")
                if not retain:
                    log(
                        "[INFO] Birth Message가 Retain이 아니므로 정상화까지 Delay 부여"
                    )
                    self.startup_delay = self.cfg["reboot_delay"]
                self.ha_offline.clear()
                self.ha_online.set()
            elif payload == b"offline":
                log("[INFO] MQTT Integration 오프라인")
                self.ha_online.clear()
                self.ha_offline.set()

    def publish(self, topic, value):
        self.mqtt.publish(topic, value)
        if self.mqtt_log:
            log("[LOG] ->> HA : {} >> {}".format(topic, value))

    # ---------- 월패드 → HA ----------
    async def on_rs485(self, data: bytes):
        self.last_received = time.time()
        if self.ew11_log:
            log("[SIGNAL] received: {}".format(data.hex().upper()))
        packets, self.residue = pk.split(self.residue + data)
        for p in packets:
            device = DEVICES.get(p.device_id)
            if device and device.handles(p):
                for reading in device.parse(p):
                    await self.apply(device, reading)

    async def apply(self, device, reading):
        name = entity(device.name, reading.id1, reading.id2)
        if name not in self.discovered:
            self.discovered.add(name)
            for payload in device.discovery(reading):
                self.register(payload)
            await asyncio.sleep(self.cfg["discovery_delay"])
        for key, value in reading.states.items():
            self.update_state(name, key, value)
        for key, value in reading.hidden.items():
            self.state[name + key] = value

    def register(self, payload):
        intg = payload.pop("_intg")
        payload["device"] = DISCOVERY_DEVICE
        payload["uniq_id"] = payload["name"]
        topic = "homeassistant/{}/ezville_wallpad/{}/config".format(
            intg, payload["name"]
        )
        log("[INFO] 장치 등록:  {}".format(topic))
        self.mqtt.publish(topic, json.dumps(payload))

    def update_state(self, name, key, value):
        if self.state.get(name + key) != value or self.force_update:
            self.state[name + key] = value
            self.publish("{}/{}/{}/state".format(HA_TOPIC, name, key), value)

    # ---------- HA → 월패드 ----------
    async def on_ha_command(self, topic, value):
        # ezville/light_01_01/power/command
        parts = topic.split("/")
        if len(parts) != 4 or parts[3] != "command":
            return
        if self.mqtt_log:
            log("[LOG] HA ->> : {} -> {}".format(topic, value))
        name, sub = parts[1], parts[2]
        try:
            kind, id1, id2 = name.split("_")
            device = BY_NAME[kind]
            id1, id2 = int(id1), int(id2)
        except (ValueError, KeyError):
            return
        # 이미 그 상태면 무시 (밝기는 꺼진 상태에서 같은 단계로 켤 수 있어 예외)
        if sub != "brightness" and self.state.get(name + sub) == value:
            return
        try:
            command = device.command(sub, value, id1, id2, self.state.get)
        except ValueError:
            log("[ERROR] 잘못된 명령: {} = {}".format(topic, value))
            return
        if command:
            if self.debug:
                log("[DEBUG] Queued ::: {}".format(command))
            await self.commands.put(command)

    async def send(self, command: Command):
        """목표 상태가 될 때까지 재전송"""
        for i in range(self.cfg["command_retry_count"]):
            if self.ew11_log:
                log("[SIGNAL] 신호 전송: {}".format(command.packet.hex().upper()))
            self.mqtt.publish(EW11_TOPIC + "/send", command.packet)
            if command.target is None:
                return

            if i == 0:
                await asyncio.sleep(self.cfg["first_waittime"])
            elif self.cfg["random_backoff"]:
                await asyncio.sleep(random.uniform(0, self.cfg["command_interval"]))
            else:
                await asyncio.sleep(self.cfg["command_interval"])

            current = self.state.get(command.key)
            if self.debug:
                log(
                    "[DEBUG] {}회: 목표 {} / 현재 {}".format(
                        i + 1, command.target, current
                    )
                )
            if current == command.target:
                return
        log(
            "[WARNING] {}회 재전송 실패, 명령 삭제: {}".format(
                self.cfg["command_retry_count"], command.packet.hex().upper()
            )
        )

    # ---------- 루프 ----------
    async def inbox_loop(self):
        while True:
            topic, payload = await self.inbox.get()
            if topic == EW11_TOPIC + "/recv":
                await self.on_rs485(payload)
            elif topic.startswith(HA_TOPIC + "/"):
                await self.on_ha_command(topic, payload.decode("utf-8", "replace"))

    async def command_loop(self):
        while True:
            await self.send(await self.commands.get())

    async def force_update_loop(self):
        """주기적으로 잠깐 동안 같은 값도 다시 발행 (HA 재시작 등으로 놓친 상태 복구)"""
        while True:
            await asyncio.sleep(self.cfg["force_update_period"])
            log("[INFO] 상태 강제 업데이트 실시")
            self.force_update = True
            await asyncio.sleep(self.cfg["force_update_duration"])
            self.force_update = False
            log("[INFO] 상태 강제 업데이트 종료")

    async def health_loop(self):
        timeout = self.cfg["ew11_timeout"]
        while True:
            await asyncio.sleep(min(timeout, 60))
            elapsed = time.time() - self.last_received
            if elapsed > timeout:
                log(
                    "[WARNING] {:.0f}초간 신호를 받지 못했습니다 (timeout: {:.0f}초). 앱을 재시작합니다.".format(
                        elapsed, timeout
                    )
                )
                sys.exit(0)

    async def run(self):
        self.loop = asyncio.get_running_loop()
        self.mqtt.connect_async(self.cfg["mqtt_server"])
        self.mqtt.loop_start()

        while True:
            if self.cfg["reboot_control"]:
                log("[INFO] Waiting for MQTT Integration online")
                await self.ha_online.wait()
            await asyncio.sleep(self.startup_delay)
            log("[INFO] 장치 등록 및 상태 업데이트를 시작합니다")

            loops = [self.inbox_loop(), self.command_loop(), self.health_loop()]
            if self.cfg["force_update_mode"]:
                loops.append(self.force_update_loop())
            tasks = [asyncio.ensure_future(c) for c in loops]

            if not self.cfg["reboot_control"]:
                await asyncio.gather(*tasks)

            # reboot_control: HA MQTT 통합이 오프라인이 되면 처음부터 다시 등록
            await self.ha_offline.wait()
            log("[WARNING] 동작 중 MQTT Integration Offline 변경, 재시작")
            for t in tasks:
                t.cancel()
            self.reset()


if __name__ == "__main__":
    with open(OPTIONS_FILE) as f:
        options = json.load(f)
    asyncio.run(Wallpad(options).run())
