"""한국 라디오: 미디어 브라우저에 채널 목록, HLS → MP3 변환 프록시 (HomePod/pyatv는 HLS 재생 불가)"""
import asyncio
import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import callback
import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .channels import CHANNELS, resolve

DOMAIN = "korean_radio"
# korean_radio:
#   speakers: {거실: media_player.geosil_4}  → media_player.korean_radio (사운드 모드 = 스피커)
CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Any(None, {vol.Optional("speakers"): {str: cv.entity_id}})}, extra=vol.ALLOW_EXTRA
)
_LOGGER = logging.getLogger(__name__)


# HomePod는 RAOP 스트림이라 HA 정지 버튼(MRP)이 안 먹음 → 해당 스피커 서비스 호출 시 ffmpeg를 꺼서 스트림 종료
STOP_SERVICES = {"play_media", "media_stop", "media_pause", "media_play_pause", "turn_off"}


async def async_setup(hass, config):
    procs = hass.data[DOMAIN] = {}  # entity_id → ffmpeg

    @callback
    def on_service(event):
        if event.data["domain"] != "media_player" or event.data["service"] not in STOP_SERVICES:
            return
        ids = event.data["service_data"].get("entity_id") or []
        for eid in [ids] if isinstance(ids, str) else ids:
            if (proc := procs.pop(eid, None)) and proc.returncode is None:
                proc.kill()

    hass.bus.async_listen(EVENT_CALL_SERVICE, on_service)
    hass.http.register_view(RadioView())
    if speakers := (config[DOMAIN] or {}).get("speakers"):
        hass.async_create_task(async_load_platform(hass, "media_player", DOMAIN, {"speakers": speakers}, config))
    return True


class RadioView(HomeAssistantView):
    # 인증 필요: media_player가 재생할 때 HA가 URL에 서명(authSig)을 붙여줌
    url = "/api/korean_radio/{player}/{cid}.mp3"
    name = "api:korean_radio"

    async def get(self, request, player, cid):
        if cid not in CHANNELS:
            raise web.HTTPNotFound
        src = await resolve(async_get_clientsession(request.app["hass"]), cid)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "error", "-i", src,
            "-vn", "-c:a", "libmp3lame", "-b:a", "192k",
            # Xing/ID3 헤더가 있으면 pyatv(miniaudio)가 'failed to init decoder'
            "-write_xing", "0", "-id3v2_version", "0", "-f", "mp3", "-",
            stdout=asyncio.subprocess.PIPE,
        )
        procs = request.app["hass"].data[DOMAIN]
        procs[player] = proc
        resp = web.StreamResponse(headers={"Content-Type": "audio/mpeg", "icy-name": CHANNELS[cid][0]})
        try:
            await resp.prepare(request)
            while chunk := await proc.stdout.read(16384):
                await resp.write(chunk)
        except ConnectionError:
            pass  # 플레이어가 끊음
        finally:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            if procs.get(player) is proc:
                del procs[player]
            _LOGGER.debug("%s 종료 (ffmpeg %s)", cid, proc.returncode)
        return resp
