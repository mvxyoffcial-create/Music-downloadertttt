import asyncio
import os
import re
import aiohttp
import urllib.parse

DOWNLOAD_TMP = "/tmp/musicbot_dl"
os.makedirs(DOWNLOAD_TMP, exist_ok=True)

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://piped-api.garudalinux.org",
    "https://pipedapi.adminforge.de",
    "https://api.piped.yt",
]


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)[:80]


def _extract_video_id(url: str) -> str:
    for p in [r"youtu\.be/([^?&\s]+)", r"[?&]v=([^&\s]+)", r"shorts/([^?&\s]+)"]:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return ""


def _duration_to_sec(duration_str: str) -> int:
    try:
        parts = str(duration_str).split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(parts[0])
    except Exception:
        return 0


# ─── SEARCH ─────────────────────────────────────────────────────────────────

async def search_youtube(query: str, max_results: int = 10):
    """Try multiple search backends until one works."""

    # 1. JioSaavn (works best for music)
    try:
        r = await _search_saavn(query, max_results)
        if r:
            return r
    except Exception:
        pass

    # 2. Piped
    try:
        r = await _search_piped(query, max_results)
        if r:
            return r
    except Exception:
        pass

    # 3. YouTube oEmbed + scrape titles via innertube
    try:
        r = await _search_innertube(query, max_results)
        if r:
            return r
    except Exception:
        pass

    return []


async def _search_saavn(query: str, max_results: int):
    """JioSaavn search — works with multiple known endpoints."""
    endpoints = [
        f"https://saavn.dev/api/search/songs?query={urllib.parse.quote(query)}&limit={max_results}",
        f"https://jiosaavn-api-privatecvc2.vercel.app/search/songs?query={urllib.parse.quote(query)}&limit={max_results}",
        f"https://jiosaavn-api-ts.vercel.app/search/songs?query={urllib.parse.quote(query)}&limit={max_results}",
    ]
    async with aiohttp.ClientSession() as session:
        for url in endpoints:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)

                    # Handle different response shapes
                    songs = (
                        data.get("data", {}).get("results")
                        or data.get("data", {}).get("songs", {}).get("results")
                        or data.get("songs", {}).get("results")
                        or data.get("results")
                        or []
                    )

                    if not songs:
                        continue

                    results = []
                    for song in songs[:max_results]:
                        duration_sec = int(song.get("duration", 0) or 0)
                        mins, secs = divmod(duration_sec, 60)
                        images = song.get("image", [])
                        thumbnail = images[-1].get("url", "") if images else ""
                        artists = song.get("artists", {}).get("primary", [])
                        artist_name = artists[0].get("name", "Unknown") if artists else song.get("primaryArtists", "Unknown")
                        dl_urls = song.get("downloadUrl") or song.get("media_url") or []
                        results.append({
                            "id": song.get("id", ""),
                            "title": song.get("name") or song.get("song", "Unknown"),
                            "url": song.get("id", ""),
                            "duration": f"{mins}:{secs:02d}",
                            "channel": artist_name,
                            "thumbnail": thumbnail,
                            "source": "saavn",
                            "download_url": _best_saavn_url(dl_urls) if isinstance(dl_urls, list) else str(dl_urls),
                        })
                    if results:
                        return results
            except Exception:
                continue
    return []


def _best_saavn_url(download_urls: list) -> str:
    if not download_urls:
        return ""
    quality_order = {"320kbps": 4, "160kbps": 3, "96kbps": 2, "48kbps": 1, "12kbps": 0}
    try:
        best = max(download_urls, key=lambda x: quality_order.get(x.get("quality", ""), 0))
        return best.get("url", "")
    except Exception:
        return ""


async def _search_piped(query: str, max_results: int):
    async with aiohttp.ClientSession() as session:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/search?q={urllib.parse.quote(query)}&filter=music_songs"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
                    items = data.get("items", [])[:max_results]
                    results = []
                    for item in items:
                        duration_sec = item.get("duration", 0) or 0
                        mins, secs = divmod(int(duration_sec), 60)
                        vid_id = item.get("url", "").replace("/watch?v=", "")
                        if not vid_id:
                            continue
                        results.append({
                            "id": vid_id,
                            "title": item.get("title", "Unknown"),
                            "url": f"https://youtu.be/{vid_id}",
                            "duration": f"{mins}:{secs:02d}",
                            "channel": item.get("uploaderName", "Unknown"),
                            "thumbnail": item.get("thumbnail") or f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg",
                            "source": "piped",
                            "download_url": "",
                        })
                    if results:
                        return results
            except Exception:
                continue
    return []


async def _search_innertube(query: str, max_results: int):
    """YouTube InnerTube API — no API key needed."""
    url = "https://www.youtube.com/youtubei/v1/search"
    payload = {
        "query": query,
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20231121.08.00",
            }
        }
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-YouTube-Client-Name": "1",
        "X-YouTube-Client-Version": "2.20231121.08.00",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=12)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json(content_type=None)

    results = []
    try:
        contents = (
            data["contents"]["twoColumnSearchResultsRenderer"]
            ["primaryContents"]["sectionListRenderer"]["contents"]
        )
        for section in contents:
            items = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in items:
                vid = item.get("videoRenderer")
                if not vid:
                    continue
                vid_id = vid.get("videoId", "")
                title = vid.get("title", {}).get("runs", [{}])[0].get("text", "Unknown")
                channel = vid.get("ownerText", {}).get("runs", [{}])[0].get("text", "Unknown")
                duration_text = vid.get("lengthText", {}).get("simpleText", "0:00")
                thumbnails = vid.get("thumbnail", {}).get("thumbnails", [])
                thumbnail = thumbnails[-1]["url"] if thumbnails else f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"
                results.append({
                    "id": vid_id,
                    "title": title,
                    "url": f"https://youtu.be/{vid_id}",
                    "duration": duration_text,
                    "channel": channel,
                    "thumbnail": thumbnail,
                    "source": "piped",
                    "download_url": "",
                })
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break
    except Exception:
        pass
    return results


# ─── AUDIO DOWNLOAD ──────────────────────────────────────────────────────────

async def download_audio(song: dict, output_path: str = DOWNLOAD_TMP):
    source = song.get("source", "piped")

    # Saavn direct MP3 link
    if source == "saavn" and song.get("download_url"):
        try:
            return await _download_direct(song["download_url"], song, output_path)
        except Exception:
            pass

    # Piped stream
    video_id = _extract_video_id(song.get("url", "")) or song.get("id", "")
    if video_id:
        try:
            return await _audio_piped(video_id, song, output_path)
        except Exception:
            pass

    raise Exception("All download methods failed")


async def _download_direct(url: str, song: dict, output_path: str):
    title = _safe_filename(song.get("title", "audio"))
    file_path = f"{output_path}/{title}.mp3"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.jiosaavn.com/",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=180),
                               allow_redirects=True) as resp:
            if resp.status != 200:
                raise Exception(f"Direct download failed: {resp.status}")
            with open(file_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(65536):
                    f.write(chunk)

    # Verify it's a real audio file
    if not os.path.exists(file_path) or os.path.getsize(file_path) < 10000:
        raise Exception("Downloaded file too small, likely invalid")

    return file_path, {
        "title": song.get("title", "Unknown"),
        "uploader": song.get("channel", "Unknown"),
        "duration": _duration_to_sec(song.get("duration", "0:00")),
    }


async def _audio_piped(video_id: str, song: dict, output_path: str):
    data = await _get_piped_stream(video_id)
    if not data:
        raise Exception("Piped: no stream data")

    streams = sorted(data.get("audioStreams", []),
                     key=lambda x: x.get("bitrate", 0), reverse=True)
    if not streams:
        raise Exception("Piped: no audio streams")

    stream_url = streams[0].get("url")
    if not stream_url:
        raise Exception("Piped: empty stream URL")

    title = _safe_filename(data.get("title", video_id))
    raw_path = f"{output_path}/{title}.webm"
    mp3_path = f"{output_path}/{title}.mp3"

    async with aiohttp.ClientSession() as session:
        async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=180)) as resp:
            if resp.status != 200:
                raise Exception(f"Piped stream error: {resp.status}")
            with open(raw_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(65536):
                    f.write(chunk)

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", raw_path, "-vn",
        "-ar", "44100", "-ac", "2", "-b:a", "192k", mp3_path,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await proc.communicate()

    try:
        os.remove(raw_path)
    except Exception:
        pass

    if not os.path.exists(mp3_path):
        raise Exception("FFmpeg conversion failed")

    return mp3_path, {
        "title": data.get("title", video_id),
        "uploader": data.get("uploader", "Unknown"),
        "duration": data.get("duration", 0),
    }


# ─── VIDEO DOWNLOAD ──────────────────────────────────────────────────────────

async def download_video(song: dict, output_path: str = DOWNLOAD_TMP):
    video_id = _extract_video_id(song.get("url", "")) or song.get("id", "")
    if not video_id:
        raise Exception("No video ID found")
    return await _video_piped(video_id, output_path)


async def _video_piped(video_id: str, output_path: str):
    data = await _get_piped_stream(video_id)
    if not data:
        raise Exception("Piped: no stream data")

    video_streams = data.get("videoStreams", [])
    if not video_streams:
        raise Exception("Piped: no video streams")

    def res_key(s):
        try:
            return int(s.get("quality", "0p").replace("p", ""))
        except Exception:
            return 0

    video_streams.sort(key=res_key, reverse=True)
    chosen = next((s for s in video_streams if res_key(s) <= 720), video_streams[-1])
    stream_url = chosen.get("url")
    if not stream_url:
        raise Exception("Piped: no video stream URL")

    audio_streams = sorted(data.get("audioStreams", []),
                           key=lambda x: x.get("bitrate", 0), reverse=True)
    title = _safe_filename(data.get("title", video_id))
    vid_raw = f"{output_path}/{title}_v.webm"
    aud_raw = f"{output_path}/{title}_a.webm"
    mp4_path = f"{output_path}/{title}.mp4"

    async with aiohttp.ClientSession() as session:
        async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=300)) as resp:
            with open(vid_raw, "wb") as f:
                async for chunk in resp.content.iter_chunked(65536):
                    f.write(chunk)

        has_audio = False
        if audio_streams and chosen.get("videoOnly", True):
            aud_url = audio_streams[0].get("url")
            if aud_url:
                async with session.get(aud_url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    with open(aud_raw, "wb") as f:
                        async for chunk in resp.content.iter_chunked(65536):
                            f.write(chunk)
                has_audio = True

    cmd = (
        ["ffmpeg", "-y", "-i", vid_raw, "-i", aud_raw, "-c:v", "copy", "-c:a", "aac", mp4_path]
        if has_audio else
        ["ffmpeg", "-y", "-i", vid_raw, "-c", "copy", mp4_path]
    )
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await proc.communicate()

    for f in [vid_raw, aud_raw]:
        try:
            os.remove(f)
        except Exception:
            pass

    if not os.path.exists(mp4_path):
        raise Exception("FFmpeg merge failed")

    return mp4_path, {
        "title": data.get("title", video_id),
        "uploader": data.get("uploader", "Unknown"),
        "duration": data.get("duration", 0),
        "width": chosen.get("width", 1280),
        "height": chosen.get("height", 720),
    }


# ─── PIPED STREAM HELPER ─────────────────────────────────────────────────────

async def _get_piped_stream(video_id: str):
    async with aiohttp.ClientSession() as session:
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/streams/{video_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None)
            except Exception:
                continue
    return None


# ─── THUMBNAIL ───────────────────────────────────────────────────────────────

async def get_thumbnail(song: dict) -> bytes:
    thumbnail_url = song.get("thumbnail", "")
    if not thumbnail_url:
        vid_id = song.get("id", "")
        thumbnail_url = f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(thumbnail_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception:
        pass
    return None
