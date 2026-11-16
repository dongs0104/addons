"""이지빌 RS485 패킷: [F7][장치 ID][방][명령][길이][데이터...][XOR][ADD]"""

from typing import List, NamedTuple, Tuple

START = 0xF7
HEADER_LEN = 5  # F7, 장치, 방, 명령, 길이


class Packet(NamedTuple):
    device_id: int
    room: int
    cmd: int
    data: bytes
    raw: bytes


def checksum(body: bytes) -> bytes:
    """체크섬 2바이트: 전체 XOR, (전체 합 + XOR)의 하위 바이트"""
    xor = 0
    for b in body:
        xor ^= b
    return bytes([xor, (sum(body) + xor) & 0xFF])


def build(device_id: int, room: int, cmd: int, data) -> bytes:
    body = bytes([START, device_id, room, cmd, len(data), *data])
    return body + checksum(body)


def split(buffer: bytes) -> Tuple[List[Packet], bytes]:
    """버퍼에서 체크섬이 맞는 패킷을 모두 꺼내고, 미완성 꼬리를 돌려준다."""
    packets = []
    i = 0
    while True:
        i = buffer.find(START, i)
        if i < 0:
            return packets, b""
        if len(buffer) - i < HEADER_LEN:
            return packets, buffer[i:]
        end = i + HEADER_LEN + buffer[i + 4] + 2
        if end > len(buffer):
            return packets, buffer[i:]
        raw = buffer[i:end]
        if checksum(raw[:-2]) != raw[-2:]:
            i += 1  # 데이터 안의 F7이었음, 다음 F7부터 다시
            continue
        packets.append(Packet(raw[1], raw[2], raw[3], raw[HEADER_LEN:-2], raw))
        i = end
