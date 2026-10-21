"""
=============================================================================
7G ULTIMATE TELEGRAM BOT (REFACTORED & ENHANCED PRODUCTION VERSION)
=============================================================================
Features:
  - Instagram Video/Reel Downloader (yt-dlp + VKR fallback)
  - Multi-Tier TikTok HD Downloader (TikWM Watermark-Free + Fallback API + yt-dlp)
  - Meta AI Chat Assistant & Image Generation (/ai, /image)
  - Advanced User Activity Tracking (Messages, Download Links, Referrals)
  - Admin Dashboard (/stats, /users) with Serialized History & Smart Pagination
  - Single User Deep Inspection (/userinfo <user_id>)
  - System Maintenance Mode (/maintenance) with Instant Automatic User Broadcast
  - Ban & Unban System (/ban, /unban) with Mandatory User Notifications
  - Admin Broadcast Engine (/broadcast <message>) with Delivery Counter
  - Flask Keep-Alive Server for 24/7 Hosting (Render, Railway, VPS, Heroku)
=============================================================================
"""

from __future__ import annotations

import base64
import html
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import requests
from flask import Flask
import telebot
import yt_dlp

# ----------------- LOGGING CONFIGURATION ----------------- #
LOG = logging.getLogger("streamly_7g")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

def log(message: str, *args: Any) -> None:
    LOG.info(message, *args)

def log_error(message: str, *args: Any) -> None:
    LOG.error(message, *args)

# ----------------- ENVIRONMENT & CONFIGURATION ----------------- #
BOT_TOKEN = os.getenv("BOT_TOKEN", "7678905793:AAGkOBkpJAoA7ur1SDQ-0xoWx8VyRICWbRM").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "6162953772"))
META_AI_KEY = os.getenv("META_AI_API_KEY", "nxt_3a454c41e6a84aeead28d1fb4aec87a4").strip()

META_AI_GEM_ID = os.getenv("META_AI_GEM_ID", "ba0fbe0d-976e-493a-afdb-6d8469e53df0")
META_AI_ENDPOINT = f"https://nxtai.zipohostbd.workers.dev/api/use?gem={META_AI_GEM_ID}"
IMAGE_FALLBACK_ENDPOINT = "https://image.pollinations.ai/prompt/"
TIKWM_ENDPOINT = "https://www.tikwm.com/api/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

MAX_TEXT_LENGTH = 3900
TELEGRAM_CHUNK_LIMIT = 3900  # Below Telegram's 4096 character limit for safety

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
USER_FILE = os.path.join(DATA_DIR, "users_db.json")
BANNED_FILE = os.path.join(DATA_DIR, "banned_users.json")
CONFIG_FILE = os.path.join(DATA_DIR, "bot_config.json")

# Initialize TeleBot and Flask Web Server
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)
app = Flask(__name__)

# Concurrency & Synchronization
FILE_LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="7g_worker")

# ----------------- FLASK KEEP-ALIVE SERVER ----------------- #
@app.route("/")
def home():
    return "✨ 7G Main Bot is Online & Running 24/7!"

@app.route("/healthz")
def healthz():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

def run_flask():
    """Runs lightweight web server to satisfy hosting port bindings (Render/Railway)."""
    port = int(os.environ.get("PORT", 10000))
    log(f"Starting Flask keep-alive server on port {port}...")
    try:
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except Exception as e:
        log_error("Flask server encountered error: %s", e)

# ----------------- UTILITY FUNCTIONS ----------------- #
def escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)

def escape_markdown(text: Any) -> str:
    s = str(text or "")
    for ch in ("_", "*", "`", "[", "]"):
        s = s.replace(ch, f"\\{ch}")
    return s

def chunk_and_send(chat_id: int, text: str, parse_mode: str = "Markdown") -> None:
    if not text:
        return
    if len(text) <= TELEGRAM_CHUNK_LIMIT:
        try:
            bot.send_message(chat_id, text, parse_mode=parse_mode)
        except Exception:
            bot.send_message(chat_id, text)
        return

    lines = text.split("\n")
    current_chunk: list[str] = []
    current_length = 0

    for line in lines:
        if current_length + len(line) + 1 > TELEGRAM_CHUNK_LIMIT:
            chunk_body = "\n".join(current_chunk)
            try:
                bot.send_message(chat_id, chunk_body, parse_mode=parse_mode)
            except Exception:
                bot.send_message(chat_id, chunk_body)
            time.sleep(0.3)
            current_chunk = [line]
            current_length = len(line) + 1
        else:
            current_chunk.append(line)
            current_length += len(line) + 1

    if current_chunk:
        chunk_body = "\n".join(current_chunk)
        try:
            bot.send_message(chat_id, chunk_body, parse_mode=parse_mode)
        except Exception:
            bot.send_message(chat_id, chunk_body)

# ----------------- DATABASE MANAGEMENT (THREAD-SAFE) ----------------- #
def load_data(filepath: str) -> Any:
    with FILE_LOCK:
        if not os.path.exists(filepath):
            return {} if "users" in filepath or "config" in filepath else []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_error(f"Error reading {filepath}: {e}")
            return {} if "users" in filepath or "config" in filepath else []

def save_data(filepath: str, data: Any) -> None:
    with FILE_LOCK:
        try:
            temp_path = f"{filepath}.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, filepath)
        except Exception as e:
            log_error(f"Data Save Error on {filepath}: {e}")

def get_config() -> dict[str, Any]:
    config = load_data(CONFIG_FILE)
    if not isinstance(config, dict):
        config = {"maintenance": False}
        save_data(CONFIG_FILE, config)
    return config

def is_banned(user_id: int | str) -> bool:
    banned_list = load_data(BANNED_FILE)
    if not isinstance(banned_list, list):
        banned_list = []
    return str(user_id) in [str(u) for u in banned_list]

def track_user_activity(user: telebot.types.User, action_type: str, text_data: str = "", referred_by: str | None = None) -> None:
    user_id = str(user.id)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with FILE_LOCK:
        users_db = load_data(USER_FILE)
        if not isinstance(users_db, dict):
            users_db = {}

        if user_id not in users_db:
            users_db[user_id] = {
                "first_name": user.first_name or "Unknown",
                "username": f"@{user.username}" if user.username else "No Username",
                "language_code": getattr(user, "language_code", None) or "N/A",
                "first_seen": now_str,
                "last_seen": now_str,
                "msg_count": 1,
                "downloads_count": 1 if "Download" in action_type else 0,
                "messages": [text_data] if text_data and "Download" not in action_type else [],
                "download_links": [text_data] if ("Download" in action_type and text_data) else [],
                "referred_by": referred_by,
                "referrals": [],
                "points": 0,
            }
        else:
            profile = users_db[user_id]
            profile["last_seen"] = now_str
            profile["msg_count"] = profile.get("msg_count", 0) + 1
            if user.first_name:
                profile["first_name"] = user.first_name
            if user.username:
                profile["username"] = f"@{user.username}"

            if "messages" not in profile or not isinstance(profile["messages"], list):
                profile["messages"] = []
            if "download_links" not in profile or not isinstance(profile["download_links"], list):
                profile["download_links"] = []

            if "Download" in action_type:
                profile["downloads_count"] = profile.get("downloads_count", 0) + 1
                if text_data:
                    profile["download_links"].append(text_data)
            else:
                if text_data:
                    profile["messages"].append(text_data)

        save_data(USER_FILE, users_db)

    EXECUTOR.submit(send_admin_alert, user, action_type, text_data, users_db[user_id])

def send_admin_alert(user: telebot.types.User, action_type: str, text_data: str, user_info: dict[str, Any]) -> None:
    try:
        preview_data = text_data[:300] + ("..." if len(text_data) > 300 else "")
        alert_msg = (
            f"🚨 *Bot Activity Alert*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Name:* {escape_markdown(user_info.get('first_name', 'Unknown'))}\n"
            f"🔗 *Username:* {escape_markdown(user_info.get('username', 'No Username'))}\n"
            f"🆔 *User ID:* `{user.id}`\n"
            f"💬 *Total Messages:* `{user_info.get('msg_count', 0)}`\n"
            f"📥 *Total Downloads:* `{user_info.get('downloads_count', 0)}`\n"
            f"⚡ *Action:* {escape_markdown(action_type)}\n"
            f"📌 *Data:* `{escape_markdown(preview_data)}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(ADMIN_ID, alert_msg, parse_mode="Markdown")
    except Exception as e:
        log_error("Failed to send admin activity alert: %s", e)

# ----------------- DOWNLOAD ENGINES ----------------- #
def download_instagram(url: str) -> str | None:
    ydl_opts = {
        "format": "best",
        "quiet": True,
        "no_warnings": True,
        "simulate": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                if "url" in info:
                    return info["url"]
                elif "entries" in info and len(info["entries"]) > 0:
                    entry = info["entries"][0]
                    return entry.get("url") or entry.get("requested_formats", [{}])[0].get("url")
    except Exception as e:
        log("Instagram yt-dlp extractor attempt skipped: %s", e)

    clean_url = url.split("?")[0]
    try:
        api_url = f"https://api.vkrdown.com/insta/?url={clean_url}"
        res = requests.get(api_url, timeout=12).json()
        if isinstance(res, dict) and "data" in res and res["data"]:
            first_media = res["data"][0]
            if isinstance(first_media, dict) and first_media.get("url"):
                return first_media.get("url")
    except Exception as e:
        log_error("Instagram VKR fallback failed: %s", e)

    return None

def resolve_tiktok_tikwm(source_url: str) -> tuple[str, str]:
    endpoint = f"{TIKWM_ENDPOINT}?{urlencode({'url': source_url, 'hd': '1'})}"
    response = json_request(endpoint, timeout=30)
    if not isinstance(response, dict):
        raise RuntimeError("TikWM returned invalid response")

    code = response.get("code")
    if code not in (0, "0", None):
        msg = response.get("msg") or "TikWM service error"
        raise RuntimeError(f"TikWM error: {msg}")

    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("TikWM returned empty payload")

    title = str(data.get("title") or "TikTok Video")
    video_url = data.get("hdplay") or data.get("play") or data.get("wmplay")
    if not video_url:
        raise RuntimeError("TikWM did not contain a valid video link")

    return title, video_url

def resolve_tiktok_fallback_api(source_url: str) -> tuple[str, str]:
    endpoint = f"https://api.tiklydown.eu.org/api/download?url={quote(source_url)}"
    headers = {"User-Agent": USER_AGENT}
    res = requests.get(endpoint, headers=headers, timeout=25)
    if res.status_code == 200:
        data = res.json()
        title = data.get("title") or "TikTok Video"
        video_url = data.get("video", {}).get("noWatermark") or data.get("video", {}).get("watermark")
        if video_url:
            return title, video_url

    raise RuntimeError("Secondary TikTok API could not resolve this URL")

def resolve_tiktok_ytdlp(source_url: str) -> tuple[str, str]:
    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        "simulate": True,
        "http_headers": {"User-Agent": USER_AGENT},
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(source_url, download=False)
        if not info:
            raise RuntimeError("yt-dlp returned no video info")
        title = info.get("title") or "TikTok Video"
        url = info.get("url")
        if url:
            return title, url

    raise RuntimeError("yt-dlp extraction failed for TikTok")

def download_tiktok(source_url: str) -> tuple[str, str]:
    errors: list[str] = []
    try:
        return resolve_tiktok_tikwm(source_url)
    except Exception as e:
        errors.append(f"TikWM: {e}")

    try:
        return resolve_tiktok_fallback_api(source_url)
    except Exception as e:
        errors.append(f"Mirror API: {e}")

    try:
        return resolve_tiktok_ytdlp(source_url)
    except Exception as e:
        errors.append(f"yt-dlp: {e}")

    log_error("All TikTok resolvers failed for URL %s: %s", source_url, " | ".join(errors))
    raise RuntimeError("Unable to download this TikTok video. The link may be private or unavailable.")

# ----------------- ADMIN COMMANDS ----------------- #
@bot.message_handler(commands=["stats", "users"])
def handle_admin_stats(message: telebot.types.Message):
    if message.chat.id != ADMIN_ID:
        return

    users_db = load_data(USER_FILE)
    if not isinstance(users_db, dict) or not users_db:
        bot.reply_to(message, "📂 *Database is currently empty.*", parse_mode="Markdown")
        return

    total_users = len(users_db)
    total_downloads = sum(u.get("downloads_count", 0) for u in users_db.values())
    total_messages = sum(u.get("msg_count", 0) for u in users_db.values())

    header = (
        f"👑 *ADMIN DASHBOARD — USER ACTIVITY DATABASE*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Total Registered Users:* `{total_users}`\n"
        f"📥 *Total Global Downloads:* `{total_downloads}`\n"
        f"💬 *Total Global Messages:* `{total_messages}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    user_blocks: list[str] = [header]
    for index, (uid, info) in enumerate(users_db.items(), start=1):
        name = escape_markdown(info.get("first_name", "Unknown"))
        uname = escape_markdown(info.get("username", "No Username"))
        dl_count = info.get("downloads_count", 0)
        msg_count = info.get("msg_count", 0)
        first_seen = info.get("first_seen", "N/A")
        last_seen = info.get("last_seen", "N/A")

        messages_list = info.get("messages", [])
        if messages_list:
            serialized_msgs = "\n".join(
                [f"    {i}. \"{escape_markdown(m[:120])}\"" for i, m in enumerate(messages_list, start=1)]
            )
        else:
            serialized_msgs = "    _(No standalone text messages)_"

        links_list = info.get("download_links", [])
        if links_list:
            serialized_links = "\n".join(
                [f"    {i}. `{escape_markdown(l)}`" for i, l in enumerate(links_list, start=1)]
            )
        else:
            serialized_links = "    _(No downloaded links yet)_"

        user_block = (
            f"👤 *User #{index}:* {name} ({uname})\n"
            f"🆔 *User ID:* `{uid}`\n"
            f"📅 *First Seen:* `{first_seen}` | *Last Seen:* `{last_seen}`\n"
            f"📥 *Downloads:* `{dl_count}` | 💬 *Messages:* `{msg_count}`\n"
            f"💬 *Serialized Messages List:*\n{serialized_msgs}\n"
            f"🔗 *Serialized Downloaded Links List:*\n{serialized_links}\n"
            f"──────────────────────────────\n"
        )
        user_blocks.append(user_block)

    full_output = "\n".join(user_blocks)
    chunk_and_send(message.chat.id, full_output, parse_mode="Markdown")

@bot.message_handler(commands=["maintenance"])
def handle_maintenance(message: telebot.types.Message):
    if message.chat.id != ADMIN_ID:
        return

    config = get_config()
    current_status = config.get("maintenance", False)
    new_status = not current_status
    config["maintenance"] = new_status
    save_data(CONFIG_FILE, config)

    if new_status:
        bot.reply_to(message, "🛠️ *Maintenance mode turned ON! Broadcasting notice to all users...*", parse_mode="Markdown")
        EXECUTOR.submit(broadcast_maintenance_notice, message.chat.id)
    else:
        bot.reply_to(message, "✅ *Maintenance mode turned OFF! Bot is unlocked for all users.*", parse_mode="Markdown")

@bot.message_handler(commands=["ban"])
def handle_ban_user(message: telebot.types.Message):
    if message.chat.id != ADMIN_ID:
        return
    tokens = message.text.split()
    if len(tokens) < 2:
        bot.reply_to(message, "⚠️ *Usage:* `/ban <user_id>`", parse_mode="Markdown")
        return

    target_id = str(tokens[1].strip())
    banned_list = load_data(BANNED_FILE)
    if not isinstance(banned_list, list):
        banned_list = []
    banned_list = [str(u) for u in banned_list]

    if target_id not in banned_list:
        banned_list.append(target_id)
        save_data(BANNED_FILE, banned_list)
        try:
            bot.send_message(target_id, "❌ Notice: Your access to this bot has been banned due to suspicious or unwanted activity.")
        except Exception:
            pass
        bot.reply_to(message, f"✅ *User ID `{target_id}` has been banned and notified.*", parse_mode="Markdown")

@bot.message_handler(commands=["unban"])
def handle_unban_user(message: telebot.types.Message):
    if message.chat.id != ADMIN_ID:
        return
    tokens = message.text.split()
    if len(tokens) < 2:
        bot.reply_to(message, "⚠️ *Usage:* `/unban <user_id>`", parse_mode="Markdown")
        return

    target_id = str(tokens[1].strip())
    banned_list = load_data(BANNED_FILE)
    if not isinstance(banned_list, list):
        banned_list = []
    banned_list = [str(u) for u in banned_list]

    if target_id in banned_list:
        banned_list.remove(target_id)
        save_data(BANNED_FILE, banned_list)
        try:
            bot.send_message(target_id, "✅ Notice: Your account has been unbanned. You can now use the bot again.")
        except Exception:
            pass
        bot.reply_to(message, f"✅ *User ID `{target_id}` has been unbanned and notified.*", parse_mode="Markdown")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.infinity_polling(timeout=60, long_polling_timeout=30)
