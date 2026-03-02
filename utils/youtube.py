import asyncio
import os
import re
import aiohttp
import urllib.parse
from yt_dlp import YoutubeDL

DOWNLOAD_TMP = "/tmp/musicbot_dl"
os.makedirs(DOWNLOAD_TMP, exist_ok=True)

# ─── SEARCH ─────────────────────────────────────────────────────────────────

async def search_youtube(query: str, max_results: int = 10):
    """Search via InnerTube (primary) → Saavn (music fallback)."""
    try:
        r = await _search_innertube(query, max_results)
        if r:
            return r
    except Exception:
        pass

    try:
        r = await _search_saavn(query, max_results)
        if r:
            return r
    except Exception:
        pass

    return []


async def _search_innertube(query: str, max_results: int):
    """YouTube InnerTube — no API key, no bot check."""
    url = "https://www.youtube.com/youtubei/v1/search?prettyPrint=false"
    payload = {
        "query": query,
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20240101.00.00",
                "hl": "en",
            }
        }
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json(content_type=None)

    results = []
    try:
        sections = (
            data["contents"]["twoColumnSearchResultsRenderer"]
            ["primaryContents"]["sectionListRenderer"]["contents"]
        )
        for section in sections:
            items = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in items:
                vid = item.get("videoRenderer")
                if not vid:
                    continue
                vid_id = vid.get("videoId", "")
                if not vid_id:
                    continue
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
                    "source": "youtube",
                    "download_url": "",
                })
                if len(results) >= max_results:
                    return results
    except Exception:
        pass
    return results


async def _search_saavn(query: str, max_results: int):
    """JioSaavn fallback search."""
    endpoints = [
        f"https://jiosaavn-api-privatecvc2.vercel.app/search/songs?query={urllib.parse.quote(query)}&limit={max_results}",
        f"https://saavn.dev/api/search/songs?query={urllib.parse.quote(query)}&limit={max_results}",
    ]
    async with aiohttp.ClientSession() as session:
        for url in endpoints:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
                    songs = (
                        data.get("data", {}).get("results")
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
                        artist = artists[0].get("name", "Unknown") if artists else "Unknown"
                        dl_urls = song.get("downloadUrl") or []
                        results.append({
                            "id": song.get("id", ""),
                            "title": song.get("name") or "Unknown",
                            "url": song.get("id", ""),
                            "duration": f"{mins}:{secs:02d}",
                            "channel": artist,
                            "thumbnail": thumbnail,
                            "source": "saavn",
                            "download_url": _best_saavn_url(dl_urls),
                        })
                    if results:
                        return results
            except Exception:
                continue
    return []


def _best_saavn_url(urls: list) -> str:
    if not urls:
        return ""
    order = {"320kbps": 4, "160kbps": 3, "96kbps": 2, "48kbps": 1, "12kbps": 0}
    try:
        best = max(urls, key=lambda x: order.get(x.get("quality", ""), 0))
        return best.get("url", "")
    except Exception:
        return ""


# ─── AUDIO DOWNLOAD ──────────────────────────────────────────────────────────

async def download_audio(song: dict, output_path: str = DOWNLOAD_TMP):
    """
    1. Saavn direct MP3 (fastest, best quality)
    2. yt-dlp android client (bypasses bot check)
    """
    # Saavn direct download
    if song.get("source") == "saavn" and song.get("download_url"):
        try:
            return await _direct_download(song["download_url"], song, output_path)
        except Exception:
            pass

    # For YouTube source - fetch saavn equivalent first
    if song.get("source") == "youtube":
        try:
            saavn_results = await _search_saavn(song["title"], 1)
            if saavn_results and saavn_results[0].get("download_url"):
                return await _direct_download(saavn_results[0]["download_url"], song, output_path)
        except Exception:
            pass

    # yt-dlp with android client (avoids bot detection)
    vid_id = _extract_video_id(song.get("url", "")) or song.get("id", "")
    if vid_id:
        return await _ytdlp_audio(f"https://youtu.be/{vid_id}", song, output_path)

    raise Exception("All audio download methods failed")


async def _direct_download(url: str, song: dict, output_path: str):
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
                raise Exception(f"HTTP {resp.status}")
            with open(file_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(65536):
                    f.write(chunk)

    if not os.path.exists(file_path) or os.path.getsize(file_path) < 5000:
        raise Exception("File too small or missing")

    return file_path, {
        "title": song.get("title", "Unknown"),
        "uploader": song.get("channel", "Unknown"),
        "duration": _duration_to_sec(song.get("duration", "0:00")),
    }


async def _ytdlp_audio(url: str, song: dict, output_path: str):
    """yt-dlp with android client user-agent — avoids most bot checks."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": f"{output_path}/%(title)s.%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        # Android client bypasses sign-in requirement
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
                "player_skip": ["webpage", "configs", "js"],
            }
        },
        "http_headers": {
            "User-Agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
        },
        "socket_timeout": 30,
        "retries": 3,
    }
    loop = asyncio.get_event_loop()

    def _run():
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            base = os.path.splitext(ydl.prepare_filename(info))[0]
            mp3 = base + ".mp3"
            return mp3, info

    return await loop.run_in_executor(None, _run)


# ─── VIDEO DOWNLOAD ──────────────────────────────────────────────────────────

async def download_video(song: dict, output_path: str = DOWNLOAD_TMP):
    vid_id = _extract_video_id(song.get("url", "")) or song.get("id", "")
    if not vid_id:
        raise Exception("No video ID")
    return await _ytdlp_video(f"https://youtu.be/{vid_id}", output_path)


async def _ytdlp_video(url: str, output_path: str):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best[ext=mp4][height<=720]/bestvideo[height<=720]+bestaudio/best",
        "outtmpl": f"{output_path}/%(title)s.%(ext)s",
        "merge_output_format": "mp4",
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
                "player_skip": ["webpage", "configs", "js"],
            }
        },
        "http_headers": {
            "User-Agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
        },
        "socket_timeout": 30,
        "retries": 3,
    }
    loop = asyncio.get_event_loop()

    def _run():
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info), info

    file_path, info = await loop.run_in_executor(None, _run)
    # ensure mp4 extension
    if not file_path.endswith(".mp4"):
        mp4 = os.path.splitext(file_path)[0] + ".mp4"
        if os.path.exists(mp4):
            file_path = mp4
    return file_path, {
        "title": info.get("title", "Unknown"),
        "uploader": info.get("uploader", "Unknown"),
        "duration": info.get("duration", 0),
        "width": info.get("width", 0),
        "height": info.get("height", 0),
    }


# ─── THUMBNAIL ───────────────────────────────────────────────────────────────

async def get_thumbnail(song: dict) -> bytes:
    url = song.get("thumbnail") or f"https://img.youtube.com/vi/{song.get('id','')}/hqdefault.jpg"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception:
        pass
    return None


# ─── UTILS ───────────────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)[:80]


def _extract_video_id(url: str) -> str:
    for p in [r"youtu\.be/([^?&\s]+)", r"[?&]v=([^&\s]+)", r"shorts/([^?&\s]+)"]:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return ""


def _duration_to_sec(s: str) -> int:
    try:
        parts = str(s).split(":")
        return int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else int(parts[0])
    except Exception:
        return 0
