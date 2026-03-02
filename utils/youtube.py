import asyncio
import re
import aiohttp
from yt_dlp import YoutubeDL


async def search_youtube(query: str, max_results: int = 5):
    """Search YouTube and return list of results."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "default_search": "ytsearch5",
    }
    loop = asyncio.get_event_loop()

    def _search():
        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            return result.get("entries", [])

    entries = await loop.run_in_executor(None, _search)
    results = []
    for entry in entries:
        if not entry:
            continue
        duration_sec = entry.get("duration", 0) or 0
        mins, secs = divmod(int(duration_sec), 60)
        results.append({
            "id": entry.get("id", ""),
            "title": entry.get("title", "Unknown"),
            "url": f"https://youtu.be/{entry.get('id', '')}",
            "duration": f"{mins}:{secs:02d}",
            "channel": entry.get("uploader", "Unknown"),
            "thumbnail": entry.get("thumbnail") or f"https://img.youtube.com/vi/{entry.get('id', '')}/hqdefault.jpg",
        })
    return results


async def download_audio(url: str, output_path: str = "/tmp/music"):
    """Download audio from YouTube URL."""
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{output_path}/%(title)s.%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
    }

    loop = asyncio.get_event_loop()

    def _download():
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            # Change ext to mp3
            import os
            base = os.path.splitext(filename)[0]
            return base + ".mp3", info

    return await loop.run_in_executor(None, _download)


async def download_video(url: str, output_path: str = "/tmp/music"):
    """Download video from YouTube URL."""
    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": f"{output_path}/%(title)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
    }

    loop = asyncio.get_event_loop()

    def _download():
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename, info

    return await loop.run_in_executor(None, _download)


async def get_thumbnail(video_id: str) -> bytes:
    """Download thumbnail bytes for a video."""
    url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.read()
