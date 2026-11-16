"""장치별 패킷 해석 / Discovery / 명령 생성

엔티티 ID가 discovery name에서 만들어지므로 템플릿 문자열은 바꾸지 말 것.
(예: ezville_light_01_01 → light.ezville_wallpad_ezville_light_01_01)
"""

from typing import Callable, Dict, List, NamedTuple, Optional

import packet as pk

STATE = 0x81
OFF_ON = ("OFF", "ON")


class Reading(NamedTuple):
    """패킷 하나에서 읽은 장치 한 개의 상태"""

    id1: int
    id2: int
    states: Dict[str, str]  # HA로 발행
    discovery_extra: Dict[str, object] = {}


class Command(NamedTuple):
    packet: bytes
    key: str  # 완료 확인용 상태 키 (예: light_01_01power)
    target: Optional[str]  # 이 값이 되면 성공, None이면 한 번만 전송


def entity(name: str, id1: int, id2: int) -> str:
    return "{}_{:0>2d}_{:0>2d}".format(name, id1, id2)


def bit(value: int, n: int) -> str:
    return OFF_ON[value >> n & 1]


class Device:
    name = ""
    id = 0
    acks = ()  # 상태와 같은 형식이라 상태로 처리하는 ACK 명령
    templates: List[dict] = []

    def handles(self, p: pk.Packet) -> bool:
        return p.cmd == STATE or p.cmd in self.acks

    def parse(self, p: pk.Packet) -> List[Reading]:
        raise NotImplementedError

    def discovery(self, reading: Reading) -> List[dict]:
        payloads = []
        for template in self.templates:
            payload = dict(template)
            payload["~"] = payload["~"].format(reading.id1, reading.id2)
            payload["name"] = payload["name"].format(reading.id1, reading.id2)
            payload.update(reading.discovery_extra)
            payloads.append(payload)
        return payloads

    def command(
        self, sub: str, value: str, id1: int, id2: int, state: Callable
    ) -> Optional[Command]:
        return None

    def _cmd(self, sub, id1, id2, room, cmd, data, target) -> Command:
        key = entity(self.name, id1, id2) + sub
        return Command(pk.build(self.id, room, cmd, data), key, target)


class Light(Device):
    """상태 바이트: [단계<<4 | 0x02(디밍 조명) | BIT0 켜짐], 디밍은 4단계"""

    name, id, acks = "light", 0x0E, (0xC1,)
    templates = [
        {
            "_intg": "light",
            "~": "ezville/light_{:0>2d}_{:0>2d}",
            "name": "ezville_light_{:0>2d}_{:0>2d}",
            "opt": True,
            "stat_t": "~/power/state",
            "cmd_t": "~/power/command",
        }
    ]
    DIMMING = {
        "bri_stat_t": "~/brightness/state",
        "bri_cmd_t": "~/brightness/command",
        "bri_scl": 4,
        "on_cmd_type": "brightness",  # 켤 때 ON 대신 밝기 명령만 전송
    }

    def __init__(self):
        self.dimmable = set()

    def parse(self, p):
        room = p.room & 0x0F
        readings = []
        for i, v in enumerate(p.data[1:], 1):
            states = {"power": bit(v, 0)}
            extra = {}
            if v & 0x02:
                self.dimmable.add((room, i))
                extra = self.DIMMING
                if v & 1:
                    states["brightness"] = str(v >> 4)
            readings.append(Reading(room, i, states, discovery_extra=extra))
        return readings

    def command(self, sub, value, id1, id2, state):
        if sub == "brightness":
            level = max(0, min(4, int(float(value))))
            if level == 0:
                return self._cmd(
                    "power", id1, id2, 0x10 | id1, 0x41, [id2, 0, 0], "OFF"
                )
            data, target = level << 4 | 1, str(level)
        elif sub == "power":
            data, target = int(value == "ON"), value
            if data and (id1, id2) in self.dimmable:
                # 디밍 조명 ON: 마지막 단계(없으면 최대)로 켜기
                last = state(entity(self.name, id1, id2) + "brightness") or "4"
                data = int(last) << 4 | 1
        else:
            return None
        return self._cmd(sub, id1, id2, 0x10 | id1, 0x41, [id2, data, 0], target)


def decode_temp(b: int) -> str:
    """BIT7은 0.5도"""
    t = (b & 0x7F) + (0.5 if b & 0x80 else 0)
    return str(t) if b & 0x80 else str(int(t))


class Thermostat(Device):
    """데이터: [에러][난방 비트맵][외출 비트맵][예약][온수][설정,현재]*방수, BIT0 = 1번 방"""

    name, id, acks = "thermostat", 0x36, (0xC4,)
    templates = [
        {
            "_intg": "climate",
            "~": "ezville/thermostat_{:0>2d}_{:0>2d}",
            "name": "ezville_thermostat_{:0>2d}_{:0>2d}",
            "mode_cmd_t": "~/power/command",
            "mode_stat_t": "~/power/state",
            "temp_stat_t": "~/setTemp/state",
            "temp_cmd_t": "~/setTemp/command",
            "curr_temp_t": "~/curTemp/state",
            "modes": ["heat", "off"],  # 외출 모드는 off로 매핑
            "min_temp": "5",
            "max_temp": "40",
        }
    ]

    def parse(self, p):
        d = p.data
        return [
            Reading(
                room,
                1,
                {
                    "power": "heat" if d[1] >> (room - 1) & 1 else "off",
                    "curTemp": decode_temp(d[4 + 2 * room]),
                    "setTemp": decode_temp(d[3 + 2 * room]),
                },
            )
            for room in range(1, (len(d) - 5) // 2 + 1)
        ]

    def command(self, sub, value, id1, id2, state):
        room = 0x10 | id1
        if sub == "power" and value in ("heat", "off"):
            # 난방 끄기 = 외출 모드
            cmd = 0x43 if value == "heat" else 0x45
            return self._cmd(sub, id1, id2, room, cmd, [1], value)
        if sub == "setTemp":
            # 월패드가 0.5도 설정을 처리하지 않아 정수로만 전송
            t = int(float(value))
            return self._cmd(sub, id1, id2, room, 0x44, [t], str(t))
        return None


class Plug(Device):
    """플러그당 3바이트: BIT23 자동모드, BIT20 전원, 하위 20비트 BCD 전력(xxxx.x W)"""

    name, id = "plug", 0x39
    templates = [
        {
            "_intg": "switch",
            "~": "ezville/plug_{:0>2d}_{:0>2d}",
            "name": "ezville_plug_{:0>2d}_{:0>2d}",
            "stat_t": "~/power/state",
            "cmd_t": "~/power/command",
            "icon": "mdi:leaf",
        },
        {
            "_intg": "binary_sensor",
            "~": "ezville/plug_{:0>2d}_{:0>2d}",
            "name": "ezville_plug-automode_{:0>2d}_{:0>2d}",
            "stat_t": "~/auto/state",
            "icon": "mdi:leaf",
        },
        {
            "_intg": "sensor",
            "~": "ezville/plug_{:0>2d}_{:0>2d}",
            "name": "ezville_plug_{:0>2d}_{:0>2d}_powermeter",
            "stat_t": "~/current/state",
            "unit_of_meas": "W",
            "device_class": "power",
        },
    ]

    def handles(self, p):
        return p.cmd == STATE  # ACK에는 상태가 없음

    def parse(self, p):
        readings = []
        for i in range(1, (len(p.data) - 1) // 3 + 1):
            v = int.from_bytes(p.data[3 * i - 2 : 3 * i + 1], "big")
            watt = sum((v >> (16 - 4 * n) & 0xF) * 10 ** (3 - n) for n in range(5))
            readings.append(
                Reading(
                    p.room >> 4,
                    i,
                    {
                        "power": bit(v, 20),
                        "auto": bit(v, 23),
                        "current": "{:.1f}".format(watt),
                    },
                )
            )
        return readings

    def command(self, sub, value, id1, id2, state):
        if sub != "power":
            return None
        data = 0x11 if value == "ON" else 0x10
        return self._cmd(sub, id1, id2, id1 << 4 | id2, 0x41, [data], value)


class GasValve(Device):
    name, id, acks = "gasvalve", 0x12, (0xC1,)
    templates = [
        {
            "_intg": "switch",
            "~": "ezville/gasvalve_{:0>2d}_{:0>2d}",
            "name": "ezville_gasvalve_{:0>2d}_{:0>2d}",
            "stat_t": "~/power/state",
            "cmd_t": "~/power/command",
            "icon": "mdi:valve",
        }
    ]

    def parse(self, p):
        # ponytail: 0x01만 ON으로 봄. 실측 값은 0x22 (의미 미확인)
        return [Reading(1, 1, {"power": "ON" if p.data[1] == 1 else "OFF"})]

    def command(self, sub, value, id1, id2, state):
        # 잠그기(OFF)만 가능
        if sub != "power" or value != "OFF":
            return None
        return self._cmd(sub, id1, id2, id1, 0x41, [0], value)


class Energy(Device):
    """원격검침. 방 03 = 전기: [에러][현재 W, BCD 3바이트][누적 0.1kWh, BCD 4바이트]
    방 02(가스/수도로 추정)는 단위 미확인이라 제외"""

    name, id = "energy", 0x30
    templates = [
        {
            "_intg": "sensor",
            "~": "ezville/energy_{:0>2d}_{:0>2d}",
            "name": "ezville_energy_{:0>2d}_{:0>2d}_power",
            "stat_t": "~/power/state",
            "unit_of_meas": "W",
            "device_class": "power",
            "state_class": "measurement",
        },
        {
            "_intg": "sensor",
            "~": "ezville/energy_{:0>2d}_{:0>2d}",
            "name": "ezville_energy_{:0>2d}_{:0>2d}_usage",
            "stat_t": "~/usage/state",
            "unit_of_meas": "kWh",
            "device_class": "energy",
            "state_class": "total_increasing",
        },
    ]

    def handles(self, p):
        return p.cmd == STATE and p.room == 0x03 and len(p.data) == 8

    def parse(self, p):
        try:
            watt, usage = int(p.data[1:4].hex()), int(p.data[4:8].hex())
        except ValueError:  # BCD가 아닌 값
            return []
        return [
            Reading(
                p.room, 1, {"power": str(watt), "usage": "{:.1f}".format(usage / 10)}
            )
        ]


class Fan(Device):
    """환기(전열교환기). 상태/ACK: [에러][전원][풍량 1~3][모드][00]
    명령: 0x41 전원, 0x42 풍량, 0x43 모드 (명령 번호 = 바꾸는 바이트)"""

    name, id, acks = "fan", 0x32, (0xC1, 0xC2, 0xC3)
    MODES = {1: "전열", 3: "바이패스"}  # 2026-11-16 실측
    templates = [
        {
            "_intg": "fan",
            "~": "ezville/fan_{:0>2d}_{:0>2d}",
            "name": "ezville_fan_{:0>2d}_{:0>2d}",
            "stat_t": "~/power/state",
            "cmd_t": "~/power/command",
            "pct_stat_t": "~/speed/state",
            "pct_cmd_t": "~/speed/command",
            "spd_rng_min": 1,
            "spd_rng_max": 3,
            "pr_mode_stat_t": "~/mode/state",
            "pr_mode_cmd_t": "~/mode/command",
            "pr_modes": list(MODES.values()),
            "icon": "mdi:air-filter",
        }
    ]

    def parse(self, p):
        d = p.data
        states = {"power": bit(d[1], 0)}
        if d[1]:
            states["speed"] = str(d[2])
        if d[3] in self.MODES:
            states["mode"] = self.MODES[d[3]]
        return [Reading(p.room, 1, states)]

    def command(self, sub, value, id1, id2, state):
        if sub == "power":
            on = int(value == "ON")
            return self._cmd(sub, id1, id2, id1, 0x41, [on], value)
        if sub == "speed":
            speed = int(float(value))
            if speed == 0:
                return self._cmd("power", id1, id2, id1, 0x41, [0], "OFF")
            return self._cmd(
                sub, id1, id2, id1, 0x42, [min(speed, 3)], str(min(speed, 3))
            )
        if sub == "mode":
            code = {v: k for k, v in self.MODES.items()}.get(value)
            if code:
                return self._cmd(sub, id1, id2, id1, 0x43, [code], value)
        return None


DEVICES = {
    d.id: d
    for d in (Light(), Thermostat(), Plug(), GasValve(), Energy(), Fan())
}
BY_NAME = {d.name: d for d in DEVICES.values()}
