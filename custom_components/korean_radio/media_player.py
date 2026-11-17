"""'한국 라디오' 미디어 플레이어: 소스 = 채널, 사운드 모드 = 재생할 스피커 (타일 드롭다운 2개로 제어)"""
import asyncio

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature as F,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from . import DOMAIN
from .channels import CHANNELS

NAME_TO_ID = {name: cid for cid, (name, _) in CHANNELS.items()}


async def async_setup_platform(hass, config, add_entities, discovery_info=None):
    add_entities([KoreanRadio(discovery_info["speakers"])])


class KoreanRadio(MediaPlayerEntity, RestoreEntity):
    _attr_name = "Korean Radio"  # HomeKit 광고 이름에서 한글이 지워져 영문 (HA 타일·홈 앱에서 이름 변경)
    _attr_unique_id = DOMAIN
    _attr_icon = "mdi:radio"
    # 리시버 = HomeKit에서 입력 소스(채널) 선택 가능한 기기 (accessory 모드로 따로 페어링)
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_volume_step = 0.05
    _attr_media_content_type = MediaType.MUSIC
    _attr_supported_features = (
        F.SELECT_SOURCE | F.SELECT_SOUND_MODE | F.PLAY | F.STOP | F.TURN_ON | F.TURN_OFF | F.VOLUME_SET | F.VOLUME_STEP
    )

    def __init__(self, speakers):
        self._speakers = speakers  # 이름 → media_player entity_id
        self._attr_source_list = list(NAME_TO_ID)
        self._attr_sound_mode_list = list(speakers)
        self._attr_source = self._attr_source_list[0]
        self._attr_sound_mode = self._attr_sound_mode_list[0]
        self._active = False  # 우리가 틀었고 아직 안 껐음

    @property
    def _speaker(self):
        return self._speakers[self._attr_sound_mode]

    async def async_added_to_hass(self):
        # 재시작해도 마지막 채널/스피커는 기억 (스트림은 끊기므로 재생 상태는 복원 안 함)
        if (last := await self.async_get_last_state()) is not None:
            if last.attributes.get("source") in NAME_TO_ID:
                self._attr_source = last.attributes["source"]
            if last.attributes.get("sound_mode") in self._speakers:
                self._attr_sound_mode = last.attributes["sound_mode"]
        self.async_on_remove(async_track_state_change_event(
            self.hass, list(self._speakers.values()), callback(lambda _: self.async_write_ha_state())))

    @property
    def state(self):
        sp = self.hass.states.get(self._speaker)
        # ponytail: 라디오 재생 중 HomePod에서 다른 음악을 틀면 그것도 '재생 중'으로 보임
        if not self._active:
            return MediaPlayerState.OFF  # HomeKit은 off가 아니면 켜진 걸로 표시
        return MediaPlayerState.PLAYING if sp and sp.state == "playing" else MediaPlayerState.IDLE

    @property
    def extra_state_attributes(self):
        # off면 HA가 source/sound_mode를 숨김 → 타일 드롭다운이 비고 재시작 복원도 안 돼서 직접 노출
        return {"source": self._attr_source, "sound_mode": self._attr_sound_mode}

    @property
    def media_title(self):
        return self._attr_source if self._active else None

    @property
    def volume_level(self):
        sp = self.hass.states.get(self._speaker)
        return sp and sp.attributes.get("volume_level")

    async def _call(self, service, entity_id, **data):
        # apple_tv play_media는 스트림이 끝날 때까지 반환 안 하므로 기다리지 않음 (blocking=False)
        await self.hass.services.async_call("media_player", service, {"entity_id": entity_id, **data})

    async def async_media_play(self):
        sp = self.hass.states.get(self._speaker)
        if self._active and sp and sp.state == "playing":
            # pyatv는 이전 스트림이 끝나기 전 새 스트림을 'already streaming'으로 거절 → 정지 후 대기
            await self._call("media_stop", self._speaker)
            for _ in range(50):  # 최대 10초
                await asyncio.sleep(0.2)
                if (sp := self.hass.states.get(self._speaker)) is None or sp.state != "playing":
                    break
            await asyncio.sleep(1)  # ponytail: idle 반영 후 pyatv 해제까지 여유, 그래도 거절되면 늘릴 것
        self._active = True
        await self._call("play_media", self._speaker,
                         media_content_id=f"media-source://{DOMAIN}/{NAME_TO_ID[self._attr_source]}",
                         media_content_type=MediaType.MUSIC)
        self.async_write_ha_state()

    async def async_media_stop(self):
        self._active = False
        await self._call("media_stop", self._speaker)  # __init__.py 리스너가 ffmpeg 종료
        self.async_write_ha_state()

    async_turn_on = async_media_play
    async_turn_off = async_media_stop

    async def async_select_source(self, source):
        self._attr_source = source
        await self.async_media_play()

    async def async_select_sound_mode(self, sound_mode):
        if self._active:
            await self._call("media_stop", self._speaker)
            self._attr_sound_mode = sound_mode
            await self.async_media_play()
        else:
            self._attr_sound_mode = sound_mode
            self.async_write_ha_state()

    async def async_set_volume_level(self, volume):
        await self._call("volume_set", self._speaker, volume_level=volume)
