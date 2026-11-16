"""python3 test_ezville.py — 2026-11-16 집 월패드 실측 패킷으로 파싱/명령 검증"""

import asyncio

import ezville
import packet as pk

# 실측 상태 패킷 (조명 4개 방, 난방, 플러그, 가스, 원격검침 전기, 환기)
CAPTURED = [
    "f70e11810500020200016d0e",
    "f70e1281030000006904",
    "f70e13810200006904",
    "f70e14810200006e0a",
    "f7361f810d00000f000016181619171817185c00",
    "f7391f8107001000481000001f5e",
    "f7393f810700900000100062958e",
    "f7398f8104009000005428",
    "f712018102002245f4",
    "f73003810800000746001696008c38",  # 원격검침 전기: 746 W, 16960.0 kWh
    "f7320181050001030100" "43f8",  # 환기: 켜짐, 강풍, 전열
]

CFG = dict(
    DEBUG_LOG=False,
    MQTT_LOG=False,
    EW11_LOG=False,
    mqtt_id="",
    mqtt_password="",
    discovery_delay=0,
    reboot_control=False,
)


async def main():
    w = ezville.Wallpad(CFG)
    sent = []
    w.mqtt.publish = lambda topic, value, retain=False: sent.append((topic, value))

    # 패킷 분리: 쓰레기 바이트, 데이터 속 F7, 조각난 수신에도 정상 분리
    stream = bytes.fromhex("00f7aa" + "".join(CAPTURED))
    for i in range(0, len(stream), 7):
        await w.on_rs485(stream[i : i + 7])
    assert w.residue == b""

    s = {t: v for t, v in sent if t.endswith("/state")}
    expect = {
        "ezville/light_01_01/power/state": "OFF",
        "ezville/light_01_04/power/state": "ON",
        "ezville/light_02_02/power/state": "OFF",
        "ezville/light_04_01/power/state": "OFF",
        "ezville/thermostat_01_01/power/state": "off",
        "ezville/thermostat_01_01/setTemp/state": "22",
        "ezville/thermostat_01_01/curTemp/state": "24",
        "ezville/thermostat_02_01/curTemp/state": "25",
        "ezville/thermostat_04_01/setTemp/state": "23",
        "ezville/plug_01_01/power/state": "ON",
        "ezville/plug_01_01/auto/state": "OFF",
        "ezville/plug_01_01/current/state": "4.8",
        "ezville/plug_03_01/auto/state": "ON",
        "ezville/plug_03_02/current/state": "6.2",
        "ezville/plug_08_01/auto/state": "ON",
        "ezville/gasvalve_01_01/power/state": "OFF",
        "ezville/energy_03_01/power/state": "746",
        "ezville/energy_03_01/usage/state": "16960.0",
        "ezville/fan_01_01/power/state": "ON",
        "ezville/fan_01_01/speed/state": "3",
        "ezville/fan_01_01/mode/state": "전열",
    }
    for k, v in expect.items():
        assert s.get(k) == v, (k, s.get(k), v)

    # Discovery: 엔티티 ID가 되는 이름 유지, 디밍 조명만 밝기 키
    disc = {t.split("/")[3]: t for t, _ in sent if t.endswith("/config")}
    for name in [
        "ezville_light_01_01",
        "ezville_thermostat_04_01",
        "ezville_plug_08_01",
        "ezville_plug-automode_01_01",
        "ezville_plug_01_01_powermeter",
        "ezville_gasvalve_01_01",
    ]:
        assert name in disc, name
    import json

    cfg = {t.split("/")[3]: json.loads(v) for t, v in sent if t.endswith("/config")}
    assert cfg["ezville_light_01_01"]["bri_scl"] == 4
    assert "bri_scl" not in cfg["ezville_light_01_03"]

    # HA 재시작(birth: online) → discovery 재등록 (상태는 retain)
    w.loop = asyncio.get_running_loop()
    sent.clear()
    w.dispatch("homeassistant/status", b"online", False)
    await w.on_rs485(bytes.fromhex(CAPTURED[0]))
    assert any(t.endswith("ezville_light_01_01/config") for t, _ in sent)

    # 명령: 옛 코드와 같은 패킷 (디밍은 월패드가 보낸 실측 패킷과 동일)
    async def cmd(topic, value):
        await w.on_ha_command(topic, value)
        return (
            w.commands.get_nowait().packet.hex().upper()
            if not w.commands.empty()
            else None
        )

    assert (
        await cmd("ezville/light_01_01/brightness/command", "1")
        == "F70E114103011100BA26"
    )
    assert (
        await cmd("ezville/light_01_01/brightness/command", "4")
        == "F70E114103014100EA86"
    )
    assert (await cmd("ezville/light_01_03/power/command", "ON"))[
        :16
    ] == "F70E114103030100"
    assert await cmd("ezville/light_01_04/power/command", "ON") is None  # 이미 ON
    assert (await cmd("ezville/thermostat_02_01/power/command", "heat"))[
        :12
    ] == "F73612430101"
    assert (await cmd("ezville/thermostat_02_01/setTemp/command", "24.0"))[
        :12
    ] == "F73612440118"
    assert (await cmd("ezville/plug_03_02/power/command", "OFF"))[:12] == "F73932410110"
    assert (
        await cmd("ezville/gasvalve_01_01/power/command", "ON")
    ) is None  # 열기 불가
    assert (await cmd("ezville/batch_01_01/elevator-up/command", "PRESS"))[
        :14
    ] == "F7330181030010"
    # 환기: 월패드가 보낸 실측 명령과 동일
    assert await cmd("ezville/fan_01_01/speed/command", "2") == "F7320142010285F4"
    assert await cmd("ezville/fan_01_01/mode/command", "바이패스") == "F7320143010385F6"
    assert await cmd("ezville/fan_01_01/power/command", "OFF") == "F7320141010084F0"
    assert await cmd("ezville/fan_01_01/speed/command", "0") == "F7320141010084F0"
    for c in [pk.build(0x36, 0x12, 0x44, [24])]:
        assert pk.split(c)[0][0].data == bytes([24])
    print("OK")


asyncio.run(main())
