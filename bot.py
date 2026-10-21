"""
=============================================================================
7G ULTIMATE TELEGRAM MASTER BOT (ENTERPRISE PRODUCTION EDITION)
=============================================================================
Primary Token: 8767739044:AAFitpz-UPHOkpkpEiKUhvla9olYHZ5IKwc
Master Admin ID: 6162953772
Meta AI API Key: nxt_3a454c41e6a84aeead28d1fb4aec87a4
=============================================================================
"""

from __future__ import annotations

import base64
import html
import json
import logging
import os
import random
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

# Ensure unbuffered standard output for real-time logs on Render/Docker
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

import requests
from flask import Flask, jsonify
import telebot
import yt_dlp

# ----------------- LOGGING CONFIGURATION ----------------- #
LOG = logging.getLogger("7g_master")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

def log(message: str, *args: Any) -> None:
    LOG.info(message, *args)
    sys.stdout.flush()

def log_error(message: str, *args: Any) -> None:
    LOG.error(message, *args)
    sys.stderr.flush()

# ----------------- CONFIGURATION ----------------- #
MAIN_BOT_TOKEN = os.getenv("BOT_TOKEN", "8767739044:AAFitpz-UPHOkpkpEiKUhvla9olYHZ5IKwc").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "6162953772"))

META_AI_KEY = os.getenv("META_AI_API_KEY", "nxt_3a454c41e6a84aeead28d1fb4aec87a4").strip()
META_AI_GEM_ID = os.getenv("META_AI_GEM_ID", "ba0fbe0d-976e-493a-afdb-6d8469e53df0")
META_AI_ENDPOINT = f"https://nxtai.zipohostbd.workers.dev/api/use?gem={META_AI_GEM_ID}"
IMAGE_FALLBACK_ENDPOINT = "https://image.pollinations.ai/prompt/"
TIKWM_ENDPOINT = "https://www.tikwm.com/api/"
SNAPTIK_ENDPOINT = "https://snaptik.app/abc2.php"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

MAX_TEXT_LENGTH = 3900
TELEGRAM_CHUNK_LIMIT = 3900

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
USER_FILE = os.path.join(DATA_DIR, "users_db.json")
BANNED_FILE = os.path.join(DATA_DIR, "banned_users.json")
CONFIG_FILE = os.path.join(DATA_DIR, "bot_config.json")
CLONES_FILE = os.path.join(DATA_DIR, "clones_db.json")

# State & Concurrency
FILE_LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="7g_worker")
ACTIVE_CLONES: dict[str, telebot.TeleBot] = {}
AWAITING_BOT_TOKEN: set[int] = set()

# Initialize Main TeleBot instance & Flask app
bot = telebot.TeleBot(MAIN_BOT_TOKEN, parse_mode=None)
app = Flask(__name__)

# ----------------- FLASK KEEP-ALIVE SERVER ----------------- #
@app.route("/")
def home():
    return "✨ 7G Master Bot is Online & Running 24/7!"

@app.route("/healthz")
@app.route("/health")
def healthz():
    return jsonify({
        "status": "ok",
        "service": "7g_master_bot",
        "active_clones": len(ACTIVE_CLONES),
        "timestamp": datetime.now().isoformat()
    }), 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    log(f"Starting Flask keep-alive server on 0.0.0.0:{port}...")
    try:
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except Exception as e:
        log_error("Flask server error: %s", e)

# ----------------- RENDER 24/7 SELF-PING KEEP-ALIVE LOOP ----------------- #
def keep_alive_ping_loop():
    """Periodically pings the web service so Render free tier never spins down."""
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip() or os.getenv("KEEP_ALIVE_URL", "").strip()
    if not render_url:
        log("Keep-alive self-ping: Waiting for RENDER_EXTERNAL_URL or live traffic.")
        return
    
    target_url = render_url.rstrip("/") + "/healthz"
    log(f"Keep-alive self-ping loop active for {target_url} (interval: ~12 mins)")
    while True:
        time.sleep(random.uniform(11 * 60, 13 * 60))
        try:
            res = requests.get(target_url, timeout=15)
            log(f"Keep-alive ping success: HTTP {res.status_code}")
        except Exception as ping_err:
            log_error(f"Keep-alive ping warning: {ping_err}")

# ----------------- UTILITY & SAFE MESSAGING FUNCTIONS ----------------- #
def escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)

def safe_reply(bot_instance: telebot.TeleBot, message: telebot.types.Message, text: str, reply_markup: Any = None, parse_mode: str = "HTML") -> Any:
    """Safe reply function with automatic plain-text fallback to prevent Telegram formatting crashes."""
    try:
        return bot_instance.reply_to(message, text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        log_error(f"Formatted reply failed ({parse_mode}): {e}. Retrying as clean plain text...")
        try:
            clean = re.sub(r"<[^>]+>", "", text).replace("*", "").replace("`", "")
            return bot_instance.reply_to(message, clean, reply_markup=reply_markup)
        except Exception as err2:
            log_error(f"Plain text reply also failed: {err2}")
            return None

def chunk_and_send(bot_instance: telebot.TeleBot, chat_id: int, text: str, parse_mode: str = "HTML") -> None:
    """Splits messages safely into chunks under 3900 characters strictly respecting Telegram's 4096 limit."""
    if not text:
        return
    if len(text) <= TELEGRAM_CHUNK_LIMIT:
        try:
            bot_instance.send_message(chat_id, text, parse_mode=parse_mode)
        except Exception:
            clean = re.sub(r"<[^>]+>", "", text).replace("*", "").replace("`", "")
            bot_instance.send_message(chat_id, clean)
        return

    lines = text.split("\n")
    current_chunk: list[str] = []
    current_length = 0

    for line in lines:
        if current_length + len(line) + 1 > TELEGRAM_CHUNK_LIMIT:
            chunk_body = "\n".join(current_chunk)
            try:
                bot_instance.send_message(chat_id, chunk_body, parse_mode=parse_mode)
            except Exception:
                clean = re.sub(r"<[^>]+>", "", chunk_body).replace("*", "").replace("`", "")
                bot_instance.send_message(chat_id, clean)
            time.sleep(0.3)
            current_chunk = [line]
            current_length = len(line) + 1
        else:
            current_chunk.append(line)
            current_length += len(line) + 1

    if current_chunk:
        chunk_body = "\n".join(current_chunk)
        try:
            bot_instance.send_message(chat_id, chunk_body, parse_mode=parse_mode)
        except Exception:
            clean = re.sub(r"<[^>]+>", "", chunk_body).replace("*", "").replace("`", "")
            bot_instance.send_message(chat_id, clean)

# ----------------- DATABASE MANAGEMENT WITH TELEGRAM BACKUP ----------------- #
def load_data(filepath: str) -> Any:
    with FILE_LOCK:
        if not os.path.exists(filepath):
            return {} if "users" in filepath or "config" in filepath or "clones" in filepath else []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_error(f"Error loading {filepath}: {e}")
            return {} if "users" in filepath or "config" in filepath or "clones" in filepath else []

def save_data(filepath: str, data: Any, trigger_backup: bool = True) -> None:
    with FILE_LOCK:
        try:
            temp_path = f"{filepath}.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, filepath)

            # Auto Database Backup to Admin Telegram Inbox
            if trigger_backup and "users_db.json" in filepath:
                EXECUTOR.submit(dispatch_telegram_backup, filepath)
        except Exception as e:
            log_error(f"Data Save Error on {filepath}: {e}")

def dispatch_telegram_backup(filepath: str) -> None:
    try:
        with open(filepath, "rb") as bf:
            bot.send_document(
                ADMIN_ID,
                bf,
                caption="🛡️ <b>Auto Telegram Database Backup Sync</b> ✨",
                parse_mode="HTML"
            )
    except Exception as e:
        log_error(f"Telegram auto-backup failed: {e}")

def get_config() -> dict[str, Any]:
    config = load_data(CONFIG_FILE)
    if not isinstance(config, dict):
        config = {"maintenance": False}
        save_data(CONFIG_FILE, config, trigger_backup=False)
    return config

def is_banned(user_id: int | str) -> bool:
    banned_list = load_data(BANNED_FILE)
    if not isinstance(banned_list, list):
        banned_list = []
    return str(user_id) in [str(u) for u in banned_list]

def track_user_activity(user: telebot.types.User, action_type: str, text_data: str = "", referred_by: str | None = None) -> None:
    """Logs serialized messages, downloaded links, points, and sends alert to Admin."""
    try:
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
                if referred_by and referred_by in users_db and referred_by != user_id:
                    users_db[referred_by]["referrals"].append(user_id)
                    users_db[referred_by]["points"] = users_db[referred_by].get("points", 0) + 1
            else:
                profile = users_db[user_id]
                profile["last_seen"] = now_str
                profile["msg_count"] = profile.get("msg_count", 0) + 1
                if user.first_name:
                    profile["first_name"] = user.first_name
                if user.username:
                    profile["username"] = f"@{user.username}"
                if getattr(user, "language_code", None):
                    profile["language_code"] = user.language_code

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

            save_data(USER_FILE, users_db, trigger_backup=False)

        EXECUTOR.submit(send_admin_alert, user, action_type, text_data, users_db[user_id])
    except Exception as track_err:
        log_error(f"User tracking error: {track_err}")

def send_admin_alert(user: telebot.types.User, action_type: str, text_data: str, user_info: dict[str, Any]) -> None:
    try:
        preview_data = text_data[:280] + ("..." if len(text_data) > 280 else "")
        alert_msg = (
            f"🚨 <b>New Bot Activity Alert!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Name:</b> {escape(user_info.get('first_name', 'Unknown'))}\n"
            f"🔗 <b>Username:</b> {escape(user_info.get('username', 'No Username'))}\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
            f"🌐 <b>Lang:</b> <code>{escape(user_info.get('language_code', 'N/A'))}</code>\n"
            f"📅 <b>First Seen:</b> <code>{user_info.get('first_seen', 'N/A')}</code>\n"
            f"🕒 <b>Last Seen:</b> <code>{user_info.get('last_seen', 'N/A')}</code>\n"
            f"💬 <b>Total Messages:</b> <code>{user_info.get('msg_count', 0)}</code>\n"
            f"📥 <b>Total Downloads:</b> <code>{user_info.get('downloads_count', 0)}</code>\n"
            f"⚡ <b>Action:</b> {escape(action_type)}\n"
            f"📌 <b>Data:</b> <code>{escape(preview_data)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(ADMIN_ID, alert_msg, parse_mode="HTML")
    except Exception as e:
        log_error("Failed to send admin activity alert: %s", e)

# ----------------- ADVANCED DOWNLOAD ENGINES ----------------- #

def download_instagram(url: str) -> str | None:
    """
    Instagram Downloader:
    Method 1: yt-dlp direct extraction
    Method 2: VKR API alternative
    Method 3: TikWM/Snapinsta backup
    """
    clean_url = url.split("?")[0]
    
    # Method 1: yt-dlp
    ydl_opts = {'format': 'best', 'quiet': True, 'no_warnings': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                if 'url' in info:
                    return info['url']
                elif 'entries' in info and len(info['entries']) > 0:
                    return info['entries'][0].get('url')
    except Exception:
        pass

    # Method 2: VKR Alternative API
    try:
        api_url = f"https://api.vkrdown.com/insta/?url={clean_url}"
        res = requests.get(api_url, timeout=12).json()
        if isinstance(res, dict) and "data" in res and res["data"]:
            first_media = res["data"][0]
            if isinstance(first_media, dict) and first_media.get("url"):
                return first_media.get("url")
    except Exception:
        pass

    # Method 3: Snapinsta / TikWM proxy
    try:
        headers = {'User-Agent': USER_AGENT}
        res = requests.get(f"https://tikwm.com/api/?url={clean_url}", headers=headers, timeout=12).json()
        if isinstance(res, dict) and "data" in res and res["data"].get("play"):
            return res["data"]["play"]
    except Exception:
        pass

    return None

def download_tiktok(url: str) -> tuple[str, str]:
    """
    TikTok Downloader (HD Without Watermark):
    Returns: (title, direct_hd_video_url)
    Uses TikWM HD API + SnapTik backup + yt-dlp native.
    """
    # 1. TikWM HD Resolver
    try:
        api_url = f"{TIKWM_ENDPOINT}?{urlencode({'url': url, 'hd': '1'})}"
        res = requests.get(api_url, headers={"User-Agent": USER_AGENT}, timeout=15).json()
        if isinstance(res, dict) and res.get("code") == 0 and "data" in res:
            data = res["data"]
            title = str(data.get("title") or "TikTok Video")
            video_url = data.get("hdplay") or data.get("play") or data.get("wmplay")
            if video_url:
                return title, video_url
    except Exception:
        pass

    # 2. Tiklydown Mirror Backup
    try:
        endpoint = f"https://api.tiklydown.eu.org/api/download?url={quote(url)}"
        res = requests.get(endpoint, headers={"User-Agent": USER_AGENT}, timeout=15).json()
        if isinstance(res, dict):
            title = str(res.get("title") or "TikTok Video")
            video_url = res.get("video", {}).get("noWatermark") or res.get("video", {}).get("watermark")
            if video_url:
                return title, video_url
    except Exception:
        pass

    # 3. yt-dlp Native Extractor
    try:
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'quiet': True,
            'no_warnings': True,
            'http_headers': {'User-Agent': USER_AGENT}
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                title = str(info.get("title") or "TikTok Video")
                video_url = info.get("url")
                if video_url:
                    return title, video_url
    except Exception:
        pass

    raise RuntimeError("Could not resolve TikTok video link. The video may be private or restricted.")

# ----------------- META AI & IMAGE GENERATION ----------------- #

def ai_request(message: str) -> Any:
    if not META_AI_KEY:
        raise RuntimeError("META_AI_API_KEY is not configured")
    res = requests.post(
        META_AI_ENDPOINT,
        json={"api_key": META_AI_KEY, "message": message},
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=60
    )
    return res.json()

def extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("response", "reply", "message", "text", "content", "answer", "output"):
            if key in value:
                res = extract_text(value[key])
                if res:
                    return res
        for nested in value.values():
            res = extract_text(nested)
            if res:
                return res
    if isinstance(value, list):
        return "\n".join(res for item in value if (res := extract_text(item)))
    return ""

def extract_image(value: Any) -> tuple[str | None, bytes | None]:
    if isinstance(value, dict):
        for key, nested in value.items():
            lower = key.lower()
            if isinstance(nested, str) and nested.startswith(("http://", "https://")):
                if any(word in lower for word in ("image", "photo", "picture", "url", "src")):
                    return nested, None
            if isinstance(nested, str) and nested.startswith("data:image/"):
                try:
                    return None, base64.b64decode(nested.split(",", 1)[1])
                except Exception:
                    pass
            url, raw = extract_image(nested)
            if url or raw:
                return url, raw
    elif isinstance(value, list):
        for nested in value:
            url, raw = extract_image(nested)
            if url or raw:
                return url, raw
    return None, None

def fallback_image_url(prompt: str) -> str:
    cleaned = re.sub(r"\s+", " ", prompt).strip()[:650]
    return f"{IMAGE_FALLBACK_ENDPOINT}{quote(cleaned, safe='')}?width=1024&height=1024&nologo=true"

def send_ai_response(bot_instance: telebot.TeleBot, chat_id: int, prompt: str, status_id: int) -> None:
    try:
        response = ai_request(prompt)
        image_url, image_bytes = extract_image(response)
        text = extract_text(response).strip()
        is_image_cmd = prompt.lstrip().lower().startswith("/image")

        if is_image_cmd and not image_url and not image_bytes:
            clean_prompt = prompt.lstrip()[len("/image"):].strip()
            image_url = fallback_image_url(clean_prompt or "Futuristic glowing art")

        if image_url:
            bot_instance.send_photo(chat_id, image_url, caption="✨ <b>Generated by Meta AI Assistant</b>", parse_mode="HTML")
        elif image_bytes:
            bot_instance.send_photo(chat_id, image_bytes, caption="✨ <b>Generated by Meta AI Assistant</b>", parse_mode="HTML")

        if is_image_cmd:
            try:
                bot_instance.delete_message(chat_id, status_id)
            except Exception:
                bot_instance.edit_message_text("🖼️ Your image has been generated above!", chat_id, status_id)
            return

        final_text = text if text else "I have processed your query. How else may I assist you?"
        if len(final_text) > TELEGRAM_CHUNK_LIMIT:
            try:
                bot_instance.delete_message(chat_id, status_id)
            except Exception:
                pass
            chunk_and_send(bot_instance, chat_id, f"🤖 <b>AI Assistant:</b>\n\n{escape(final_text)}", parse_mode="HTML")
        else:
            bot_instance.edit_message_text(f"🤖 <b>AI Assistant:</b>\n\n{escape(final_text)}", chat_id, status_id, parse_mode="HTML")
    except Exception as error:
        log_error("AI Assistant processing error: %s", error)
        try:
            bot_instance.edit_message_text("⚠️ <i>AI Assistant is temporarily busy. Please try again in a few moments.</i>", chat_id, status_id, parse_mode="HTML")
        except Exception:
            pass

# ----------------- BOT FACTORY & HANDLER REGISTRATION ----------------- #

def get_menu_keyboard(is_clone: bool = False) -> telebot.types.ReplyKeyboardMarkup:
    """
    Builds the reply keyboard:
    - Main Bot: [📊 My Stats, 🔗 Referral Link] and [🤖 Create Own Bot]
    - Clone Bot: [📊 My Stats, 🔗 Referral Link] ONLY (sub-cloning disabled!)
    """
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if is_clone:
        markup.add(
            telebot.types.KeyboardButton("📊 My Stats"),
            telebot.types.KeyboardButton("🔗 Referral Link")
        )
    else:
        markup.add(
            telebot.types.KeyboardButton("📊 My Stats"),
            telebot.types.KeyboardButton("🔗 Referral Link")
        )
        markup.add(
            telebot.types.KeyboardButton("🤖 Create Own Bot")
        )
    return markup

def register_bot_handlers(bot_instance: telebot.TeleBot, is_clone: bool = False):
    """
    Registers all commands, link downloaders, and admin panels to any bot instance.
    Guarantees that clone bots do not contain the 'Create Own Bot' facility.
    """

    # /start handler
    @bot_instance.message_handler(commands=['start'])
    def handle_start(message: telebot.types.Message):
        if is_banned(message.chat.id):
            safe_reply(bot_instance, message, "❌ <b>Notice: You are banned from using this bot!</b>", parse_mode="HTML")
            return

        config = get_config()
        if config.get("maintenance", False) and message.chat.id != ADMIN_ID:
            safe_reply(
                bot_instance,
                message,
                "⚠️ Notice: The bot is currently undergoing system security updates and maintenance. It is temporarily unavailable. Please try again later!",
                parse_mode=None
            )
            return

        args = (message.text or "").split()
        referred_by = args[1] if len(args) > 1 and args[1].isdigit() and args[1] != str(message.chat.id) else None

        track_user_activity(message.from_user, "Start Command / New Visitor", message.text or "/start", referred_by)

        markup = get_menu_keyboard(is_clone=is_clone)
        welcome_text = (
            "✨🔥 <b>Welcome to 7G Ultimate Bot!</b> 🔥✨\n\n"
            "📥 <b>Video Downloader:</b>\n"
            "• <b>Instagram:</b> Send any Post/Reel link for instant HD download!\n"
            "• <b>TikTok:</b> Send any TikTok link for Watermark-Free HD video!\n\n"
            "🤖 <b>Meta AI Assistant:</b> Type anything or ask with <code>/ai &lt;query&gt;</code>\n"
            "🎨 <b>AI Image Generator:</b> Create pictures with <code>/image &lt;prompt&gt;</code>\n\n"
            "👇 <b>Use the buttons below for quick navigation!</b>"
        )
        safe_reply(bot_instance, message, welcome_text, reply_markup=markup, parse_mode="HTML")

    # /mystats handler
    @bot_instance.message_handler(commands=['mystats'])
    def handle_my_stats(message: telebot.types.Message):
        if is_banned(message.chat.id):
            return
        users_db = load_data(USER_FILE)
        user_info = users_db.get(str(message.chat.id), {})

        msgs = user_info.get("msg_count", 0)
        downloads = user_info.get("downloads_count", 0)
        first_seen = user_info.get("first_seen", "N/A")
        refs = len(user_info.get("referrals", []))
        points = user_info.get("points", 0)

        stats_msg = (
            f"📊 <b>Your Personal Bot Statistics</b> 🌟\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Joined Date:</b> <code>{first_seen}</code>\n"
            f"💬 <b>Total Messages Sent:</b> <code>{msgs}</code>\n"
            f"📥 <b>Total Videos Downloaded:</b> <code>{downloads}</code>\n"
            f"👥 <b>Total Referrals:</b> <code>{refs}</code> (Points: <code>{points}</code>)\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <b>Thanks for using 7G Bot!</b> ❤️"
        )
        safe_reply(bot_instance, message, stats_msg, parse_mode="HTML")

    # /stats & /users handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['stats', 'users'])
    def handle_admin_stats(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return

        users_db = load_data(USER_FILE)
        if not isinstance(users_db, dict) or not users_db:
            safe_reply(bot_instance, message, "📂 <b>Database is currently empty. No users found.</b>", parse_mode="HTML")
            return

        total_users = len(users_db)
        total_downloads = sum(u.get("downloads_count", 0) for u in users_db.values())
        total_messages = sum(u.get("msg_count", 0) for u in users_db.values())
        total_clones = len(ACTIVE_CLONES)

        header = (
            f"👑 <b>ADMIN DASHBOARD — FULL USER DATABASE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>Total Users:</b> <code>{total_users}</code>\n"
            f"📥 <b>Total Global Downloads:</b> <code>{total_downloads}</code>\n"
            f"💬 <b>Total Global Messages:</b> <code>{total_messages}</code>\n"
            f"🤖 <b>Active Cloned Bots:</b> <code>{total_clones}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        user_blocks: list[str] = [header]

        for index, (uid, info) in enumerate(users_db.items(), start=1):
            name = escape(info.get("first_name", "Unknown"))
            uname = escape(info.get("username", "No Username"))
            dl_count = info.get("downloads_count", 0)
            msg_count = info.get("msg_count", 0)
            first_seen = info.get("first_seen", "N/A")
            last_seen = info.get("last_seen", "N/A")

            # Serialized Messages List
            messages_list = info.get("messages", [])
            if messages_list:
                serialized_msgs = "\n".join(
                    [f"    {i}. \"{escape(m[:120])}\"" for i, m in enumerate(messages_list, start=1)]
                )
            else:
                serialized_msgs = "    <i>(No standalone text messages)</i>"

            # Serialized Downloaded Links List
            links_list = info.get("download_links", [])
            if links_list:
                serialized_links = "\n".join(
                    [f"    {i}. <code>{escape(l)}</code>" for i, l in enumerate(links_list, start=1)]
                )
            else:
                serialized_links = "    <i>(No downloaded links yet)</i>"

            user_block = (
                f"👤 <b>User #{index}:</b> {name} ({uname})\n"
                f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
                f"📅 <b>First Seen:</b> <code>{first_seen}</code> | <b>Last Seen:</b> <code>{last_seen}</code>\n"
                f"📥 <b>Downloads:</b> <code>{dl_count}</code> | 💬 <b>Messages:</b> <code>{msg_count}</code>\n"
                f"💬 <b>Serialized Messages List:</b>\n{serialized_msgs}\n"
                f"🔗 <b>Serialized Downloaded Links List:</b>\n{serialized_links}\n"
                f"──────────────────────────────\n"
            )
            user_blocks.append(user_block)

        full_output = "\n".join(user_blocks)
        chunk_and_send(bot_instance, message.chat.id, full_output, parse_mode="HTML")

    # /userinfo <user_id> handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['userinfo'])
    def handle_user_info(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return
        tokens = (message.text or "").split()
        if len(tokens) < 2:
            safe_reply(bot_instance, message, "⚠️ <b>Usage:</b> <code>/userinfo &lt;user_id&gt;</code>", parse_mode="HTML")
            return

        target_id = tokens[1].strip()
        users_db = load_data(USER_FILE)
        if target_id not in users_db:
            safe_reply(bot_instance, message, f"❌ <b>User ID <code>{target_id}</code> not found in database.</b>", parse_mode="HTML")
            return

        info = users_db[target_id]
        name = escape(info.get("first_name", "Unknown"))
        uname = escape(info.get("username", "No Username"))
        msg_count = info.get("msg_count", 0)
        dl_count = info.get("downloads_count", 0)
        first_seen = info.get("first_seen", "N/A")
        last_seen = info.get("last_seen", "N/A")
        referred_by = info.get("referred_by") or "None (Direct)"
        referrals = info.get("referrals", [])

        # Serialized Messages List
        messages_list = info.get("messages", [])
        if messages_list:
            serialized_msgs = "\n".join(
                [f"  {i}. \"{escape(m)}\"" for i, m in enumerate(messages_list, start=1)]
            )
        else:
            serialized_msgs = "  <i>(No text messages recorded)</i>"

        # Serialized Download Links List
        links_list = info.get("download_links", [])
        if links_list:
            serialized_links = "\n".join(
                [f"  {i}. <code>{escape(l)}</code>" for i, l in enumerate(links_list, start=1)]
            )
        else:
            serialized_links = "  <i>(No downloaded links recorded)</i>"

        details = (
            f"🔍 <b>DETAILED USER PROFILE & ACTIVITY LOG</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Name:</b> {name}\n"
            f"🔗 <b>Username:</b> {uname}\n"
            f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
            f"🌐 <b>Lang:</b> <code>{escape(info.get('language_code', 'N/A'))}</code>\n"
            f"📅 <b>Joined Date:</b> <code>{first_seen}</code>\n"
            f"⏱️ <b>Last Activity:</b> <code>{last_seen}</code>\n"
            f"👥 <b>Referred By:</b> <code>{referred_by}</code>\n"
            f"🎯 <b>Invited Users Count:</b> <code>{len(referrals)}</code>\n"
            f"💬 <b>Total Messages:</b> <code>{msg_count}</code>\n"
            f"📥 <b>Total Downloads:</b> <code>{dl_count}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💬 <b>ALL SENT MESSAGES (SERIALIZED):</b>\n{serialized_msgs}\n\n"
            f"🔗 <b>ALL DOWNLOADED LINKS (SERIALIZED):</b>\n{serialized_links}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        chunk_and_send(bot_instance, message.chat.id, details, parse_mode="HTML")

    # /maintenance handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['maintenance'])
    def handle_maintenance(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return

        config = get_config()
        current_status = config.get("maintenance", False)
        new_status = not current_status
        config["maintenance"] = new_status
        save_data(CONFIG_FILE, config, trigger_backup=False)

        if new_status:
            safe_reply(
                bot_instance,
                message,
                "🛠️ <b>Maintenance mode turned ON! Broadcasting notice to all registered users...</b>",
                parse_mode="HTML"
            )
            EXECUTOR.submit(broadcast_maintenance_notice, message.chat.id)
        else:
            safe_reply(
                bot_instance,
                message,
                "✅ <b>Maintenance mode turned OFF! The bot is now unlocked and accessible for everyone.</b>",
                parse_mode="HTML"
            )

    # /ban <user_id> handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['ban'])
    def handle_ban(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return
        tokens = (message.text or "").split()
        if len(tokens) < 2:
            safe_reply(bot_instance, message, "⚠️ <b>Usage:</b> <code>/ban &lt;user_id&gt;</code>", parse_mode="HTML")
            return

        target_id = str(tokens[1].strip())
        if target_id == str(ADMIN_ID):
            safe_reply(bot_instance, message, "⚠️ <b>Cannot ban the Admin account.</b>", parse_mode="HTML")
            return

        banned_list = load_data(BANNED_FILE)
        if not isinstance(banned_list, list):
            banned_list = []
        banned_list = [str(u) for u in banned_list]

        if target_id in banned_list:
            safe_reply(bot_instance, message, f"⚠️ <b>User ID <code>{target_id}</code> is already in the ban list.</b>", parse_mode="HTML")
            return

        banned_list.append(target_id)
        save_data(BANNED_FILE, banned_list, trigger_backup=False)

        # Send mandatory notification to banned user
        notified = False
        try:
            ban_notice = "❌ Notice: Your access to this bot has been banned due to suspicious or unwanted activity."
            bot.send_message(target_id, ban_notice)
            notified = True
        except Exception:
            pass

        notify_status = "and notified ✅" if notified else "but user could not be reached ⚠️"
        safe_reply(bot_instance, message, f"✅ <b>User ID <code>{target_id}</code> has been banned {notify_status}.</b>", parse_mode="HTML")

    # /unban <user_id> handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['unban'])
    def handle_unban(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return
        tokens = (message.text or "").split()
        if len(tokens) < 2:
            safe_reply(bot_instance, message, "⚠️ <b>Usage:</b> <code>/unban &lt;user_id&gt;</code>", parse_mode="HTML")
            return

        target_id = str(tokens[1].strip())
        banned_list = load_data(BANNED_FILE)
        if not isinstance(banned_list, list):
            banned_list = []
        banned_list = [str(u) for u in banned_list]

        if target_id not in banned_list:
            safe_reply(bot_instance, message, f"⚠️ <b>User ID <code>{target_id}</code> is not in the ban list.</b>", parse_mode="HTML")
            return

        banned_list.remove(target_id)
        save_data(BANNED_FILE, banned_list, trigger_backup=False)

        # Send mandatory notification to unbanned user
        notified = False
        try:
            unban_notice = "✅ Notice: Your account has been unbanned. You can now use the bot again."
            bot.send_message(target_id, unban_notice)
            notified = True
        except Exception:
            pass

        notify_status = "and notified ✅" if notified else "but user could not be reached ⚠️"
        safe_reply(bot_instance, message, f"✅ <b>User ID <code>{target_id}</code> has been unbanned {notify_status}.</b>", parse_mode="HTML")

    # /broadcast <message> handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['broadcast'])
    def handle_broadcast(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return

        announcement = (message.text or "")[len("/broadcast"):].strip()
        if not announcement:
            safe_reply(bot_instance, message, "⚠️ <b>Usage:</b> <code>/broadcast Your message here</code>", parse_mode="HTML")
            return

        users_db = load_data(USER_FILE)
        if not isinstance(users_db, dict) or not users_db:
            safe_reply(bot_instance, message, "❌ <b>No users found in database.</b>", parse_mode="HTML")
            return

        safe_reply(bot_instance, message, f"🚀 <b>Broadcasting announcement to {len(users_db)} users...</b>", parse_mode="HTML")
        EXECUTOR.submit(execute_broadcast, message.chat.id, announcement)

    # General incoming messages and link processor
    @bot_instance.message_handler(func=lambda message: True)
    def process_incoming_text(message: telebot.types.Message):
        if is_banned(message.chat.id):
            safe_reply(bot_instance, message, "❌ <b>Notice: Your access to this bot is currently banned.</b>", parse_mode="HTML")
            return

        config = get_config()
        if config.get("maintenance", False) and message.chat.id != ADMIN_ID:
            safe_reply(
                bot_instance,
                message,
                "⚠️ Notice: The bot is currently undergoing system security updates and maintenance. It is temporarily unavailable. Please try again later!",
                parse_mode=None
            )
            return

        text = (message.text or "").strip()

        # Handle keyboard buttons
        if text == "📊 My Stats":
            handle_my_stats(message)
            return

        elif text == "🔗 Referral Link":
            try:
                me = bot_instance.get_me()
                ref_link = f"https://t.me/{me.username}?start={message.chat.id}"
                safe_reply(
                    bot_instance,
                    message,
                    f"👥 <b>Your Personal Referral Link:</b>\n<code>{ref_link}</code>\n\n"
                    f"<i>Share this link with your friends to invite them! Each friend invited earns you reward points.</i> ✨",
                    parse_mode="HTML"
                )
            except Exception:
                safe_reply(bot_instance, message, f"🔗 <b>Your Invite ID:</b> <code>{message.chat.id}</code>", parse_mode="HTML")
            return

        # 'Create Own Bot' flow (AVAILABLE ONLY ON MAIN BOT)
        elif text == "🤖 Create Own Bot" or text == "/createbot":
            if is_clone:
                safe_reply(bot_instance, message, "⚠️ <i>This cloned bot cannot create further sub-bots.</i>", parse_mode="HTML")
                return

            AWAITING_BOT_TOKEN.add(message.chat.id)
            prompt_text = (
                "🤖 <b>Create & Host Your Own 7G Bot For FREE!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "1. Go to @BotFather on Telegram.\n"
                "2. Create a new bot with <code>/newbot</code> and copy your <b>Bot Token</b>.\n"
                "3. <b>Paste and send your Bot Token directly here in this chat!</b>\n\n"
                "⚡ <i>Your personal bot will instantly go LIVE with all Instagram, TikTok HD & AI features!</i>"
            )
            safe_reply(bot_instance, message, prompt_text, parse_mode="HTML")
            return

        # Check if user is sending a bot token for cloning
        if not is_clone and message.chat.id in AWAITING_BOT_TOKEN:
            candidate_token = text
            if re.match(r"^\d{8,12}:[a-zA-Z0-9_-]{35}$", candidate_token):
                AWAITING_BOT_TOKEN.discard(message.chat.id)
                safe_reply(bot_instance, message, "⏳ <i>Verifying token and launching your cloned bot...</i>", parse_mode="HTML")
                EXECUTOR.submit(launch_user_clone_bot, message, candidate_token)
                return
            else:
                AWAITING_BOT_TOKEN.discard(message.chat.id)

        # Explicit /ai command
        if text.startswith("/ai"):
            prompt = text[len("/ai"):].strip()
            if prompt:
                track_user_activity(message.from_user, "AI Query", text)
                status_msg = bot_instance.reply_to(message, "💭 <i>Thinking... Please wait.</i>", parse_mode="HTML")
                EXECUTOR.submit(send_ai_response, bot_instance, message.chat.id, prompt, status_msg.message_id)
            else:
                safe_reply(bot_instance, message, "⚠️ <b>Usage:</b> <code>/ai &lt;your question here&gt;</code>", parse_mode="HTML")
            return

        # Explicit /image command
        if text.startswith("/image"):
            prompt = text[len("/image"):].strip()
            if prompt:
                track_user_activity(message.from_user, "AI Image Request", text)
                status_msg = bot_instance.reply_to(message, "🎨 <i>Generating your AI image... Please wait.</i>", parse_mode="HTML")
                EXECUTOR.submit(send_ai_response, bot_instance, message.chat.id, f"/image {prompt}", status_msg.message_id)
            else:
                safe_reply(bot_instance, message, "⚠️ <b>Usage:</b> <code>/image &lt;detailed image description&gt;</code>", parse_mode="HTML")
            return

        # Instagram Downloader
        if "instagram.com" in text.lower():
            track_user_activity(message.from_user, "Instagram Download", text)
            status_msg = bot_instance.reply_to(message, "⏳ <b>Downloading Instagram media, please hold on...</b> 🚀", parse_mode="HTML")
            EXECUTOR.submit(handle_instagram_task, bot_instance, message, text, status_msg.message_id)
            return

        # TikTok Downloader (HD Watermark-Free)
        if "tiktok.com" in text.lower() or "vt.tiktok.com" in text.lower():
            track_user_activity(message.from_user, "TikTok Download", text)
            status_msg = bot_instance.reply_to(message, "⏳ <b>Downloading TikTok video without watermark...</b> 🎵", parse_mode="HTML")
            EXECUTOR.submit(handle_tiktok_task, bot_instance, message, text, status_msg.message_id)
            return

        # General Text -> AI Chat Assistant Fallback
        track_user_activity(message.from_user, "General Chat", text)
        status_msg = bot_instance.reply_to(message, "💭 <i>Thinking...</i>", parse_mode="HTML")
        EXECUTOR.submit(send_ai_response, bot_instance, message.chat.id, text, status_msg.message_id)

def handle_instagram_task(bot_instance: telebot.TeleBot, message: telebot.types.Message, url: str, status_msg_id: int):
    try:
        video_url = download_instagram(url)
        if video_url:
            caption_text = "📥 <b>Downloaded via 7G Bot</b>\n⚡ <i>Fast & High Quality</i> ✨"
            bot_instance.send_video(message.chat.id, video_url, caption=caption_text, parse_mode="HTML")
            try:
                bot_instance.delete_message(message.chat.id, status_msg_id)
            except Exception:
                pass
        else:
            bot_instance.edit_message_text(
                "❌ <b>Unfortunately, nothing was found or Instagram blocked the request. Try another link! 🥺</b>",
                message.chat.id,
                status_msg_id,
                parse_mode="HTML"
            )
    except Exception as e:
        log_error(f"Instagram download error: {e}")
        bot_instance.edit_message_text(
            "❌ <b>Video file is too large or failed to send.</b>",
            message.chat.id,
            status_msg_id,
            parse_mode="HTML"
        )

def handle_tiktok_task(bot_instance: telebot.TeleBot, message: telebot.types.Message, url: str, status_msg_id: int):
    try:
        title, video_url = download_tiktok(url)
        caption_text = f"📥 <b>{escape(title[:240])}</b>\n\n🎵 <b>TikTok HD No-Watermark</b> ✨\n⚡ <i>Downloaded via 7G Bot</i>"
        bot_instance.send_video(message.chat.id, video_url, caption=caption_text, parse_mode="HTML")
        try:
            bot_instance.delete_message(message.chat.id, status_msg_id)
        except Exception:
            pass
    except Exception as e:
        log_error(f"TikTok download error: {e}")
        bot_instance.edit_message_text(
            f"❌ <b>Failed to fetch TikTok video 🥺</b>\n<i>{escape(str(e))}</i>",
            message.chat.id,
            status_msg_id,
            parse_mode="HTML"
        )

# ----------------- BROADCAST & MAINTENANCE ENGINES ----------------- #

def broadcast_maintenance_notice(admin_chat_id: int) -> None:
    notice_text = (
        "⚠️ Notice: The bot is currently undergoing system security updates and maintenance. "
        "It is temporarily unavailable. Please try again later!"
    )
    users_db = load_data(USER_FILE)
    if not isinstance(users_db, dict):
        return

    sent = 0
    failed = 0
    for uid in users_db.keys():
        if str(uid) == str(ADMIN_ID):
            continue
        try:
            bot.send_message(uid, notice_text)
            sent += 1
            time.sleep(0.05)
        except Exception:
            failed += 1

    try:
        report = (
            f"📢 <b>Maintenance Broadcast Completed!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 <b>Delivered to:</b> <code>{sent}</code> users\n"
            f"🔴 <b>Failed/Blocked:</b> <code>{failed}</code> users\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(admin_chat_id, report, parse_mode="HTML")
    except Exception as e:
        log_error("Failed to deliver broadcast summary to admin: %s", e)

def execute_broadcast(admin_chat_id: int, content: str) -> None:
    users_db = load_data(USER_FILE)
    if not isinstance(users_db, dict):
        return

    formatted_msg = f"📢 <b>Admin Announcement:</b>\n\n{escape(content)}"
    sent = 0
    failed = 0

    for uid in users_db.keys():
        try:
            bot.send_message(uid, formatted_msg, parse_mode="HTML")
            sent += 1
            time.sleep(0.05)
        except Exception:
            failed += 1

    try:
        summary = (
            f"✅ <b>Broadcast Finished!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 <b>Sent Successfully:</b> <code>{sent}</code>\n"
            f"🔴 <b>Failed:</b> <code>{failed}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(admin_chat_id, summary, parse_mode="HTML")
    except Exception as e:
        log_error("Failed to send broadcast summary: %s", e)

# ----------------- 'CREATE OWN BOT' MULTI-BOT SYSTEM ----------------- #

def launch_user_clone_bot(message: telebot.types.Message, token: str):
    """Verifies user token, launches clone thread, and persists to clones_db.json."""
    try:
        test_bot = telebot.TeleBot(token, parse_mode=None)
        me = test_bot.get_me()
        bot_username = me.username
        bot_id = str(me.id)

        try:
            test_bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass

        # Register clone handlers (is_clone=True disables further cloning!)
        register_bot_handlers(test_bot, is_clone=True)

        with FILE_LOCK:
            clones_db = load_data(CLONES_FILE)
            if not isinstance(clones_db, dict):
                clones_db = {}
            clones_db[bot_id] = {
                "token": token,
                "username": bot_username,
                "owner_id": message.chat.id,
                "owner_name": message.from_user.first_name,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            save_data(CLONES_FILE, clones_db, trigger_backup=False)

        ACTIVE_CLONES[bot_id] = test_bot
        t = threading.Thread(target=run_clone_polling, args=(test_bot, bot_username), daemon=True)
        t.start()

        success_msg = (
            f"🎉 <b>CONGRATULATIONS! YOUR BOT IS NOW LIVE!</b> 🚀\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <b>Bot Username:</b> @{bot_username}\n"
            f"🆔 <b>Bot ID:</b> <code>{bot_id}</code>\n"
            f"⚡ <b>Status:</b> 100% Online & Hosted 24/7!\n\n"
            f"👉 <b>Open your bot now:</b> https://t.me/{bot_username}\n"
            f"<i>Your bot has Instagram, TikTok HD & AI features active right now!</i>"
        )
        safe_reply(bot, message, success_msg, parse_mode="HTML")

        bot.send_message(
            ADMIN_ID,
            f"🤖 <b>New Bot Cloned!</b>\nOwner: <code>{message.chat.id}</code> ({message.from_user.first_name})\nBot: @{bot_username}",
            parse_mode="HTML"
        )
    except Exception as e:
        log_error(f"Failed to clone bot with token {token[:10]}: {e}")
        safe_reply(
            bot,
            message,
            f"❌ <b>Failed to launch bot:</b> Invalid token or Telegram refused connection.\n<i>Details: {escape(str(e))}</i>",
            parse_mode="HTML"
        )

def run_clone_polling(clone_bot: telebot.TeleBot, username: str):
    log(f"Cloned bot @{username} polling initialized.")
    while True:
        try:
            clone_bot.infinity_polling(timeout=30, long_polling_timeout=20, skip_pending=True)
        except Exception as err:
            log_error(f"Cloned bot @{username} polling error: {err}. Reconnecting in 10s...")
            time.sleep(10)

def restore_saved_clones():
    """Restores all previously created clone bots upon master bot restart."""
    clones_db = load_data(CLONES_FILE)
    if isinstance(clones_db, dict) and clones_db:
        log(f"Restoring {len(clones_db)} active cloned bots from database...")
        for bot_id, item in clones_db.items():
            token = item.get("token")
            username = item.get("username", "UnknownBot")
            if token:
                try:
                    clone_bot = telebot.TeleBot(token, parse_mode=None)
                    try:
                        clone_bot.delete_webhook(drop_pending_updates=True)
                    except Exception:
                        pass
                    register_bot_handlers(clone_bot, is_clone=True)
                    ACTIVE_CLONES[bot_id] = clone_bot
                    t = threading.Thread(target=run_clone_polling, args=(clone_bot, username), daemon=True)
                    t.start()
                    log(f"Restored clone bot @{username} successfully.")
                except Exception as restore_err:
                    log_error(f"Failed to restore clone bot {bot_id}: {restore_err}")

# ----------------- MAIN INITIALIZATION ----------------- #
if __name__ == "__main__":
    print("=" * 65, flush=True)
    print("🚀 7G Ultimate Master Bot is launching...", flush=True)
    print(f"🤖 Primary Bot Token: {MAIN_BOT_TOKEN[:10]}...{MAIN_BOT_TOKEN[-6:]}", flush=True)
    print(f"👑 Master Admin ID: {ADMIN_ID}", flush=True)
    print("=" * 65, flush=True)

    # 1. Register handlers for the Primary Master Bot (is_clone=False)
    register_bot_handlers(bot, is_clone=False)

    # 2. Start Flask Keep-Alive Web Server on 0.0.0.0:PORT
    flask_thread = threading.Thread(target=run_flask, daemon=True, name="FlaskServerThread")
    flask_thread.start()
    time.sleep(1.5)

    # 3. Start self-ping thread for Render free web service
    ping_thread = threading.Thread(target=keep_alive_ping_loop, daemon=True, name="SelfPingThread")
    ping_thread.start()

    # 4. Clean webhook and drop pending update backlog
    try:
        log("Clearing any webhook and pending updates for clean connection...")
        bot.delete_webhook(drop_pending_updates=True)
        time.sleep(1)
        log("Webhook cleared successfully!")
    except Exception as wh_err:
        log_error(f"Webhook note: {wh_err}")

    # 5. Authenticate Master Bot
    try:
        master_info = bot.get_me()
        log(f"✅ Master Bot Authenticated: @{master_info.username} (ID: {master_info.id}, Name: {master_info.first_name})")
    except Exception as auth_err:
        log_error(f"❌ Failed to authenticate Master Bot with Telegram: {auth_err}")

    # 6. Restore all cloned bots in background threads
    EXECUTOR.submit(restore_saved_clones)

    # 7. Start Primary Bot Infinity Polling with Resilience
    log(">>> 7G MASTER BOT IS NOW FULLY ONLINE AND SERVING REQUESTS! <<<")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=20, skip_pending=False)
        except telebot.apihelper.ApiTelegramException as api_err:
            if api_err.error_code == 409:
                log_error(
                    "⚠️ TELEGRAM CONFLICT (Error 409): Another instance is running with this token! "
                    "Please stop the old bot instance on your PC or previous server. Retrying in 10s..."
                )
                time.sleep(10)
            else:
                log_error(f"Telegram API Exception: {api_err}. Retrying in 5s...")
                time.sleep(5)
        except Exception as error:
            log_error(f"Bot polling error: {error}. Reconnecting in 5s...")
            time.sleep(5)
