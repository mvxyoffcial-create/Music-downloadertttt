from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import Config


async def check_force_sub(client: Client, user_id: int):
    """Returns list of channels user hasn't joined, empty if all joined."""
    not_joined = []
    for channel in Config.FORCE_SUB_CHANNELS:
        try:
            member = await client.get_chat_member(f"@{channel}", user_id)
            if member.status.value in ("left", "banned", "kicked"):
                not_joined.append(channel)
        except Exception:
            not_joined.append(channel)
    return not_joined


def force_sub_markup(not_joined_channels):
    buttons = []
    for channel in not_joined_channels:
        buttons.append([InlineKeyboardButton(f"📢 Join @{channel}", url=f"https://t.me/{channel}")])
    buttons.append([InlineKeyboardButton("✅ Verify", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)
