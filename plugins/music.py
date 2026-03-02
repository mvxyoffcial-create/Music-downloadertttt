import os
import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from utils.youtube import search_youtube, download_audio, download_video, get_thumbnail
from utils.forcesub import check_force_sub, force_sub_markup
from config import Config
from script import script

DOWNLOAD_TMP = "/tmp/musicbot_dl"
os.makedirs(DOWNLOAD_TMP, exist_ok=True)

PER_PAGE = 5
search_cache = {}   # {user_id: {"results": [...], "query": str, "msg_id": int}}


# ─── Keyboards ───────────────────────────────────────────────────────────────

def results_keyboard(results: list, user_id: int, page: int = 0):
    total_pages = max(1, (len(results) + PER_PAGE - 1) // PER_PAGE)
    start = page * PER_PAGE
    page_results = results[start: start + PER_PAGE]

    buttons = []
    for i, r in enumerate(page_results):
        actual_idx = start + i
        title = (r["title"][:36] + "…") if len(r["title"]) > 36 else r["title"]
        buttons.append([InlineKeyboardButton(
            f"🎵 {title} [{r['duration']}]",
            callback_data=f"sel_{user_id}_{actual_idx}_{page}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"page_{user_id}_{page - 1}"))
    nav.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"page_{user_id}_{page + 1}"))
    if nav:
        buttons.append(nav)

    return InlineKeyboardMarkup(buttons)


def format_keyboard(user_id: int, idx: int, page: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎵 MP3 Audio", callback_data=f"dl_audio_{user_id}_{idx}_{page}"),
            InlineKeyboardButton("🎬 MP4 Video", callback_data=f"dl_video_{user_id}_{idx}_{page}"),
        ],
        [InlineKeyboardButton("🔙 Back to Results", callback_data=f"page_{user_id}_{page}")]
    ])


# ─── Search handler ──────────────────────────────────────────────────────────

@Client.on_message(filters.private & ~filters.command(
    ["start", "help", "about", "stats", "broadcast", "info"]))
async def music_search(client: Client, message: Message):
    not_joined = await check_force_sub(client, message.from_user.id)
    if not_joined:
        # Reply to user's message
        await message.reply_photo(
            photo=Config.WELCOME_IMG,
            caption=script.FORCE_SUB_TXT,
            reply_markup=force_sub_markup(not_joined),
            quote=True
        )
        return

    query = message.text
    if not query or query.startswith("/"):
        return

    # Reply to user's search message (auto-filter style)
    msg = await message.reply_text(
        "🔍 <b>Searching for your song...</b>",
        quote=True
    )

    try:
        results = await search_youtube(query, max_results=10)
        if not results:
            await msg.edit("❌ <b>No results found.</b>\n<i>Try a different song name.</i>")
            return

        search_cache[message.from_user.id] = {
            "results": results,
            "query": query,
            "msg_id": message.id
        }

        await msg.edit(
            text=(
                f"🔎 <b>Results for:</b> <code>{query}</code>\n"
                f"<i>Found {len(results)} results</i>\n\n"
                f"<b>👇 Select a song to download</b>"
            ),
            reply_markup=results_keyboard(results, message.from_user.id, page=0)
        )
    except Exception as e:
        await msg.edit(f"❌ <b>Search failed:</b> <code>{_clean(str(e))[:200]}</code>")


# ─── Pagination ──────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^page_(\d+)_(\d+)$"))
async def paginate(client: Client, query: CallbackQuery):
    _, user_id, page = query.data.split("_")
    user_id, page = int(user_id), int(page)

    if query.from_user.id != user_id:
        await query.answer("❌ Not your search!", show_alert=True)
        return

    cache = search_cache.get(user_id)
    if not cache:
        await query.answer("⚠️ Session expired. Search again.", show_alert=True)
        return

    results = cache["results"]
    await query.message.edit_text(
        text=(
            f"🔎 <b>Results for:</b> <code>{cache['query']}</code>\n"
            f"<b>👇 Select a song to download</b>  <i>(Page {page + 1})</i>"
        ),
        reply_markup=results_keyboard(results, user_id, page)
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^noop$"))
async def noop(client: Client, query: CallbackQuery):
    await query.answer()


# ─── Song Selected ────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^sel_(\d+)_(\d+)_(\d+)$"))
async def song_selected(client: Client, query: CallbackQuery):
    _, user_id, idx, page = query.data.split("_")
    user_id, idx, page = int(user_id), int(idx), int(page)

    if query.from_user.id != user_id:
        await query.answer("❌ Not your search!", show_alert=True)
        return

    cache = search_cache.get(user_id)
    if not cache or idx >= len(cache["results"]):
        await query.answer("⚠️ Session expired.", show_alert=True)
        return

    song = cache["results"][idx]
    await query.message.edit_text(
        text=(
            f"🎵 <b>{song['title']}</b>\n"
            f"👤 <b>Artist:</b> {song['channel']}\n"
            f"⏱️ <b>Duration:</b> {song['duration']}\n\n"
            f"<b>Choose download format 👇</b>"
        ),
        reply_markup=format_keyboard(user_id, idx, page)
    )
    await query.answer()


# ─── Download ─────────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^dl_(audio|video)_(\d+)_(\d+)_(\d+)$"))
async def do_download(client: Client, query: CallbackQuery):
    parts = query.data.split("_")
    fmt = parts[1]
    user_id = int(parts[2])
    idx = int(parts[3])
    page = int(parts[4])

    if query.from_user.id != user_id:
        await query.answer("❌ Not your session!", show_alert=True)
        return

    cache = search_cache.get(user_id)
    if not cache or idx >= len(cache["results"]):
        await query.answer("⚠️ Session expired.", show_alert=True)
        return

    song = cache["results"][idx]

    await query.message.edit_text(
        f"⬇️ <b>Downloading...</b>\n"
        f"🎵 <code>{song['title']}</code>\n"
        f"<i>Please wait ⏳</i>"
    )
    await query.answer()

    # Thumbnail
    thumb_path = None
    try:
        thumb_bytes = await get_thumbnail(song)
        if thumb_bytes:
            thumb_path = f"{DOWNLOAD_TMP}/{song['id']}_thumb.jpg"
            with open(thumb_path, "wb") as f:
                f.write(thumb_bytes)
    except Exception:
        pass

    me = await client.get_me()
    caption = (
        f"🎵 <b>{song['title']}</b>\n"
        f"👤 <b>Artist:</b> {song['channel']}\n"
        f"⏱️ <b>Duration:</b> {song['duration']}\n\n"
        f"📥 <b>Downloaded via @{me.username}</b>"
    )

    try:
        if fmt == "audio":
            file_path, info = await download_audio(song, DOWNLOAD_TMP)
            # Send as reply to the results message
            await query.message.reply_audio(
                audio=file_path,
                title=song["title"],
                performer=song["channel"],
                duration=int(info.get("duration", 0) or 0),
                thumb=thumb_path,
                caption=caption,
                quote=True
            )
        else:
            file_path, info = await download_video(song, DOWNLOAD_TMP)
            await query.message.reply_video(
                video=file_path,
                duration=int(info.get("duration", 0) or 0),
                width=info.get("width", 0),
                height=info.get("height", 0),
                thumb=thumb_path,
                caption=caption,
                quote=True
            )

        try:
            os.remove(file_path)
        except Exception:
            pass

        # Delete the "downloading..." message
        await query.message.delete()

    except Exception as e:
        err = _clean(str(e))[:300]
        await query.message.edit_text(
            f"❌ <b>Download failed!</b>\n"
            f"<code>{err}</code>\n\n"
            f"<i>Try another song.</i>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Results", callback_data=f"page_{user_id}_{page}")]
            ])
        )
    finally:
        if thumb_path:
            try:
                os.remove(thumb_path)
            except Exception:
                pass


def _clean(text: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m', '', text).strip()
