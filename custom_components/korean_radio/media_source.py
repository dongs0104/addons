from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source import BrowseMediaSource, MediaSource, PlayMedia

from . import DOMAIN
from .channels import CHANNELS


async def async_get_media_source(hass):
    return KoreanRadioSource()


class KoreanRadioSource(MediaSource):
    name = "한국 라디오"

    def __init__(self):
        super().__init__(DOMAIN)

    async def async_resolve_media(self, item):
        # 스피커는 정지 버튼 처리용 (__init__.py STOP_SERVICES). 쿼리로 넣으면 HA가 URL 서명을 안 해서 경로에 넣음
        return PlayMedia(f"/api/korean_radio/{item.target_media_player or 'browser'}/{item.identifier}.mp3", "audio/mpeg")

    async def async_browse_media(self, item):
        return BrowseMediaSource(
            domain=DOMAIN, identifier=None, media_class=MediaClass.CHANNEL,
            media_content_type=MediaType.MUSIC, title=self.name,
            can_play=False, can_expand=True, children_media_class=MediaClass.MUSIC,
            children=[
                BrowseMediaSource(
                    domain=DOMAIN, identifier=cid, media_class=MediaClass.MUSIC,
                    media_content_type="audio/mpeg", title=name,
                    can_play=True, can_expand=False,
                )
                for cid, (name, _) in CHANNELS.items()
            ],
        )
