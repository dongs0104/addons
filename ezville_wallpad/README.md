# 이지빌 월패드 RS485 Add-on (MQTT)

EW11이 RS485 패킷을 MQTT로 중계하는 구성에서, 이지빌 월패드의 조명/난방을 HA에서 조회·제어합니다.
MQTT Discovery로 장치가 자동 등록됩니다.

## 지원 장치

* 조명: 켜기/끄기, 디밍 조명은 밝기 (`light_dimming`에 등록한 조명만)
* 난방: 난방/끄기(외출 모드), 설정 온도(0.5도 단위), 현재 온도

## 준비

1. Mosquitto broker 애드온 + MQTT 통합 구성요소
2. EW11을 MQTT 모드로 설정: 수신 → `ew11/recv` 발행, `ew11/send` 구독 → RS485 송신

## 설정

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `wallpad_mode` | on | off면 제어 명령을 구독하지 않음 (조회만) |
| `light_dimming` | `1_1_1`, `1_1_2` | 밝기 조절 가능한 조명 ID (`그룹_방_번호`) |
| `rs485_mqtt.recv_topic` / `send_topic` | ew11/recv, ew11/send | EW11 MQTT 토픽 |
| `mqtt.server` / `port` / `need_login` / `user` / `passwd` | | Mosquitto 접속 정보 |
| `mqtt.discovery` | true | HA 자동 등록 |
| `mqtt.prefix` | ezville | 장치 MQTT 토픽 prefix |
| `rs485.max_retry` | 20 | ACK 없을 때 재시도 시간(초) |
| `watchdog.timeout` | 60 | 패킷 미수신 경고 시간(초), 0이면 끔 |
| `restart.time` | 04:00 | 매일 재시작 시각, 빈 값이면 끔 |
| `restart.inactivity` | 0 | N분간 패킷 없으면 재시작, 0이면 끔 |
| `log.to_file` / `filename` | true, /share/ezville_wallpad.log | 로그 파일 (자정 로테이션, 7개 보관) |

Standalone: `./run_standalone.sh` (첫 실행 시 `options_standalone.json` 생성)

패킷 분석: [DOCS_PACKETS.md](DOCS_PACKETS.md)

## 면책조항 (Disclaimer)

* 이 애드온은 무상으로 제공되므로 정확성이나 안정성 등 어떠한 보증도 제공하지 않습니다.
* 이 애드온은 오픈소스로 실행 코드와 함께 배포되므로 코드 및 동작에 대한 확인 책임은 사용자에게 있습니다.
* 기타 사항은 GPLv3를 따릅니다. [전문보기](LICENSE)

---

![카카오톡 후원 QR코드](https://github.com/n-andflash/ha_addons/raw/master/sds_wallpad/images/donation_kakao.png)
* 카카오톡 후원 코드: https://qr.kakaopay.com/281006011000008548744237 (모바일에서만 가능)

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
[armhf-shield]: https://img.shields.io/badge/armhf-yes-green.svg
[armv7-shield]: https://img.shields.io/badge/armv7-yes-green.svg
[i386-shield]: https://img.shields.io/badge/i386-yes-green.svg
