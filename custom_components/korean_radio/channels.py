"""채널 목록과 스트림 URL 해석. 출처: https://github.com/BSofDeath/radio.bsod.kr (2026-11)

URL이 kbs:/mbc:/sbs: 로 시작하면 방송사 API로 매번 토큰 URL을 받아옴 (만료되므로 캐시 안 함).
"""

CHANNELS = {
    "kbs1radio": ("KBS 1라디오", "kbs:21"),
    "kbs2radio": ("KBS 해피FM", "kbs:22"),
    "kbs3radio": ("KBS 3라디오 사랑의소리", "kbs:23"),
    "kbs1fm": ("KBS 클래식FM", "kbs:24"),
    "kbs2fm": ("KBS 쿨FM", "kbs:25"),
    "kbshanminjok": ("KBS 한민족방송", "kbs:26"),
    "mbcsfm": ("MBC 표준FM", "mbc:sfm"),
    "mbcfm4u": ("MBC FM4U", "mbc:mfm"),
    "mbcchm": ("MBC mini 올댓뮤직", "mbc:chm"),
    "sbslovefm": ("SBS 러브FM", "sbs:lovepc/lovefm"),
    "sbspowerfm": ("SBS 파워FM", "sbs:powerpc/powerfm"),
    "sbsdmb": ("SBS 고릴라디오M", "sbs:sbsdmbpc/sbsdmb"),
    "cbssfm": ("CBS 표준FM", "https://m-aac.cbs.co.kr/mweb_cbs981/_definst_/cbs981.stream/playlist.m3u8"),
    "cbsmfm": ("CBS 음악FM", "https://m-aac.cbs.co.kr/mweb_cbs939/_definst_/cbs939.stream/playlist.m3u8"),
    "cbsjoy4u": ("CBS JOY4U", "https://m-aac.cbs.co.kr/mweb_cbscmc/_definst_/cbscmc.stream/playlist.m3u8"),
    "ebsfm": ("EBS FM", "https://ebsonair.ebs.co.kr/fmradiofamilypc/familypc1m/playlist.m3u8"),
    "ebsbandi": ("EBS 반디", "https://ebsonair.ebs.co.kr/cloud1/iradio/playlist.m3u8"),
    "tbsfm": ("TBS FM", "https://cdnfm.tbs.seoul.kr/tbs/_definst_/tbs_fm_web_360.smil/playlist.m3u8"),
    "tbsefm": ("TBS eFM", "https://cdnefm.tbs.seoul.kr/tbs/_definst_/tbs_efm_web_360.smil/playlist.m3u8"),
    "tbn": ("TBN 경인교통방송", "https://www.tbn.it.kr/gyeongin/myStream/playlist.m3u8"),
    "ytn": ("YTN 라디오", "https://radiolive.ytn.co.kr/radio/_definst_/20211118_fmlive/playlist.m3u8"),
    "ifm": ("iFM 경인방송", "https://stream.ifm.kr/live/aod1/playlist.m3u8"),
    "obs": ("OBS 라디오", "https://vod3.obs.co.kr:444/live/obsstream1/radio.stream/playlist.m3u8"),
    "kookbang": ("국방FM", "https://mediaworks.dema.mil.kr/live_edge/audio.sdp/playlist.m3u8"),
    "kugak": ("국악방송", "https://mgugaklive.nowcdn.co.kr/gugakradio/gugakradio.stream/playlist.m3u8"),
    "bbs": ("BBS 불교방송", "https://bbslive.clouducs.com/bbsradio-mlive/radio.stream/playlist.m3u8"),
    "cpbc": ("CPBC 가톨릭평화방송", "http://onair1.cpbc.co.kr:1935/live/_definst_/Instreamer.stream_aac/playlist.m3u8"),
    "febc": ("FEBC 극동방송", "http://mlive2.febc.net:1935/live/seoulfm/playlist.m3u8"),
    "wbs": ("WBS 원음방송", "https://wbsradio.kr/wbs-seoul"),
    "arirang": ("Arirang Radio", "https://amdlive-ch03-ctnd-com.akamaized.net/arirang_3ch/smil:arirang_3ch.smil/playlist.m3u8"),
}


async def resolve(session, cid):
    """채널 id → 실제 스트림 URL (aiohttp session)"""
    url = CHANNELS[cid][1]
    kind, _, arg = url.partition(":")
    if kind == "kbs":
        async with session.get(f"https://cfpwwwapi.kbs.co.kr/api/v1/landing/live/channel_code/{arg}") as r:
            return (await r.json(content_type=None))["channel_item"][0]["service_url"]
    if kind == "mbc":
        async with session.get(f"https://sminiplay.imbc.com/aacplay.ashx?agent=webapp&channel={arg}") as r:
            return (await r.text()).strip()
    if kind == "sbs":
        async with session.get(f"https://apis.sbs.co.kr/play-api/1.0/livestream/{arg}?protocol=hls&ssl=Y") as r:
            return (await r.text()).strip()
    return url


if __name__ == "__main__":
    # 전 채널 해석 + ffprobe 확인: uv run --with aiohttp python3 channels.py
    import asyncio, subprocess, aiohttp

    async def main():
        async with aiohttp.ClientSession() as s:
            for cid, (name, _) in CHANNELS.items():
                try:
                    url = await resolve(s, cid)
                    p = subprocess.run(["ffprobe", "-v", "error", "-rw_timeout", "10000000", "-show_entries", "stream=codec_name", "-of", "csv=p=0", url],
                                       capture_output=True, text=True, timeout=30)
                    print(f"{'OK ' if p.returncode == 0 else 'ERR'} {cid:14} {name} {p.stdout.split() or p.stderr.strip()[:100]}")
                except Exception as e:
                    print(f"ERR {cid:14} {name} {e!r}")

    asyncio.run(main())
