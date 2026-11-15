"""python3 test_ezville_wallpad.py — 패킷 생성/파싱 자체 검사"""

import ezville_wallpad as ez

ez.Options = {
    "light_dimming": ["1_1_1"],
    "mqtt": {"prefix": "ezville", "_discovery": False},
}
sent = []
ez.mqtt.publish = lambda t, v: sent.append((t, v))

# 체크섬: 문서 예시 패킷 재현
assert ez.make_packet(0x0E, 0x11, 0x41, [1, 1, 0]).hex() == "f70e114103010100aa06"
assert ez.serial_verify_checksum(bytes.fromhex("f70e11810400010000" + "6c08"))

# 조명 밝기 명령: 4단계 → 0x41 (실측), 0 → 끔
ez.mqtt_device(["ezville", "light", "1_1_1", "brightness"], "4")
ez.mqtt_device(["ezville", "light", "1_1_1", "brightness"], "0")
ez.mqtt_device(["ezville", "light", "1_1_2", "power"], "ON")
assert [p[6] for p in ez.serial_queue] == [0x41, 0x00, 0x01]
assert all(ez.serial_verify_checksum(p) for p in ez.serial_queue)
ez.serial_queue.clear()

# 난방: heat → 0x43, off → 외출 0x45, 23.5도 → 0x97
ez.mqtt_device(["ezville", "thermostat", "1_2", "power"], "heat")
ez.mqtt_device(["ezville", "thermostat", "1_2", "power"], "off")
ez.mqtt_device(["ezville", "thermostat", "1_2", "target"], "23.5")
assert [(p[2], p[3], p[5]) for p in ez.serial_queue] == [
    (0x12, 0x43, 1),
    (0x12, 0x45, 1),
    (0x12, 0x44, 0x97),
]

# 상태 파싱: 1_1_1 밝기 8로 켜짐, 1_1_2 꺼짐
ez.serial_receive_state(
    "light", ez.make_packet(0x0E, 0x11, 0x81, [0, 0x33, 0x02, 0x00])
)
st = dict(sent)
assert (
    st["ezville/light/1_1_1/power/state"] == "ON"
    and st["ezville/light/1_1_1/brightness/state"] == 3
)
assert (
    st["ezville/light/1_1_2/power/state"] == "OFF"
    and "ezville/light/1_1_2/brightness/state" not in st
)

# 난방 상태: 문서 예시 (1번 방 설정 0x14=20, 현재 0x15=21)
ez.serial_receive_state(
    "thermostat", bytes.fromhex("f7361f810f800b1400001415181805160d140500c1d6")
)
assert dict(sent)["ezville/thermostat/1_1/target/state"] == 20
assert dict(sent)["ezville/thermostat/1_1/current/state"] == 21
assert ez.decode_temp(0x97) == 23.5
print("OK")
