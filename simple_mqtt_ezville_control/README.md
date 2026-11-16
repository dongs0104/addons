# MQTT 기반 Simple EzVille Wallpad Control

## 1. 지원 기능

  - 조명, 난방 (외출 모드), 대기전력차단, 엘리베이터콜 상태 조회 및 제어 지원
  - 대기전력소모, 현관 스위치 상태 (외출 모드, 그룹 조명) 센서 지원
  - MQTT 기반 장치 자동 Discovery 지원

## 2. 설치 방법

  - 애드온 스토어 -> 저장소 -> [https://github.com/ktdo79/addons](https://github.com/ktdo79/addons) 추가하기 
  - MQTT 기반 Simple EzVille Wallpad Control 설치

> 사전에 MQTT Integration 및 Mosquitto Broker Addon 설치 필수

## 3. 설정 방법

### 3.1. EW11 설정

#### 3.1.1. Serial Port 설정

  - Buffer Size를 128로 변경 

#### 3.1.2. Communication Settings 설정

##### 3.1.2.1. MQTT 설정

  - +Add를 누르고 MQTT 추가 
  - Server 주소 = Home Assistant IP 주소, Port는 Mosquitto Broker 설정 Port, Buffer Size는 128 로 설정
  - Subscribe Topic는 ew11/send, Publish Topic은 ew11/recv 로 설정
  - Mosquitto Broker에 ID/Password가 있으면 MQTT Account, Password에 기입

##### 3.1.2.2. netp 설정

  - Buffer Size를 128로 변경

### 3.2. 애드온 설정

  - DEBUG_LOG / MQTT_LOG / EW11_LOG (체크 박스): 디버그 / HA 송수신 / RS485 패킷 로그
  - mqtt_server, mqtt_id, mqtt_password: Mosquitto Broker 주소와 계정
  - command_interval (초): 명령이 안 먹히는 경우 재시도 간격 (기본값 0.5초)
  - command_retry_count (횟수): 명령 최대 재시도 횟수 (기본값 30회)
  - first_waittime (초): 첫 명령 후 상태 확인까지 대기 (기본값 0.5초)
  - random_backoff (체크 박스): 재시도 간격을 0 ~ command_interval 사이 랜덤으로
  - discovery_delay (초): MQTT Discovery로 장치 등록 후 대기 시간 (기본값 0.2초)
  - force_update_mode / force_update_period / force_update_duration: 주기(기본 10분)마다 잠깐(기본 2초) 같은 상태도 다시 발행
  - reboot_control / reboot_delay: HA MQTT 통합이 오프라인→온라인 되면 처음부터 다시 등록 (Birth Message가 retain이 아니면 reboot_delay초 대기)
  - ew11_timeout (초): 이 시간 동안 RS485 패킷이 없으면 애드온 재시작 (기본값 1시간)

### 3.3. 지원 장치

  - 조명 (디밍 조명은 상태 바이트 0x02 비트로 자동 감지, 4단계 밝기)
  - 난방 (난방/외출, 설정 온도는 정수)
  - 대기전력 차단 콘센트 (전원, 자동모드, 전력 W)
  - 환기 (켜기/끄기, 약·중·강, 전열/바이패스)
  - 원격검침 전기 (집 전체 실시간 W, 누적 kWh)
  - 가스밸브 (잠그기만 가능), 일괄차단기 (엘리베이터 호출)
