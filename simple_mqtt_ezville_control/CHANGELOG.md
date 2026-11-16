수정 사항 Changelog

v 0.0.7 (2026-11-16)
* EW11 무신호 timeout 시 종료 코드를 1로 변경: 0이면 Supervisor가 재시작하지 않고 정지 상태로 남던 문제 (애드온 Watchdog 켜야 재시작)
* mqtt_password를 password 타입으로 (UI에서 가려짐)

v 0.0.6 (2026-11-16)
* HA 재시작 시 월패드 엔티티가 모두 unavailable 되던 문제: homeassistant/status=online 수신 시 discovery 재등록 + 상태 재발행

v 0.0.5 (2026-11-16)
* 환기(전열교환기, 0x32) 추가: 켜기/끄기, 풍량 약·중·강, 모드 전열/바이패스

v 0.0.4 (2026-11-16)
* 집 전체 전력 원격검침(장치 0x30, 방 03) 추가: 실시간 W, 누적 kWh (BCD)

v 0.0.3 (2026-11-16)
* 코드 구조 정리: packet.py(패킷) / devices.py(장치별 클래스) / ezville.py(MQTT·루프), 엔티티 ID·토픽은 동일
* 패킷 분리를 바이트 단위로 변경 (hex 문자열 1글자 단위 탐색으로 데이터 속 F7에 잘못 맞춰지던 문제)
* socket/mixed 모드 재연결 시 TypeError로 죽던 문제 수정 (asyncio 소켓으로 교체)
* DEBUG_LOG 켜면 죽던 문제 수정, 자기 송신 토픽(ew11/send) 구독 제거
* 난방 온도 BIT7(0.5도) 해석, 설정은 정수로만 전송
* Python 3.8(buster, 지원 종료) → 3.12

v 0.0.2 (2026-11-16)
* 조명 4단계 디밍: 상태 바이트 0x02 비트로 디밍 조명 자동 감지, HA 밝기 슬라이더 지원 (기존 조명1·2 F1 하드코딩 제거)
* 디밍 조명을 켜면 마지막 단계로 켜짐
* 플러그 전력 센서 device_class energy → power (W 단위와 맞지 않아 HA가 거부하던 문제)

v 0.0.1
