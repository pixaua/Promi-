from __future__ import annotations

import base64
import html
import json
import logging
import os
import random
import re
import signal
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen
from datetime import datetime
from flask import Flask
import telebot
import yt_dlp
import requests

LOG = logging.getLogger("streamly")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

# ----------------- CONFIGURATION ----------------- #
BOT_TOKEN = "8767739044:AAFitpz-UPHOkpkpEiKUhvla9olYHZ5IKwc"  # Telegram Bot Token
ADMIN_ID = 6162953772                # Admin User ID
META_AI_KEY = os.getenv("META_AI_API_KEY", "nxt_3a454c41e6a84aeead28d1fb4aec87a4").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

META_AI_GEM_ID = "ba0fbe0d-976e-493a-afdb-6d8469e53df0"
META_AI_ENDPOINT = f"https://nxtai.zipohostbd.workers.dev/api/use?gem={META_AI_GEM_ID}"
IMAGE_FALLBACK_ENDPOINT = "https://image.pollinations.ai/prompt/"
TIKWM_ENDPOINT = "https://www.tikwm.com/api/"
SNAPTIK_ENDPOINT = "https://snaptik.app/abc2.php"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

MAX_MEDIA_BYTES = max(8, int(os.getenv("MAX_MEDIA_MB", "48"))) * 1024 * 1024
MAX_VIDEO_SECONDS = max(60, int(os.getenv("MAX_VIDEO_MINUTES", "30"))) * 60
STATE_TTL_SECONDS = 20 * 60
MAX_TEXT_LENGTH = 3900

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
USER_FILE = os.path.join(DATA_DIR, "users_db.json")
BANNED_FILE = os.path.join(DATA_DIR, "banned_users.json")
CONFIG_FILE = os.path.join(DATA_DIR, "bot_config.json")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

CHAT_MODES: dict[int, str] = {}
DOWNLOAD_OPTIONS: dict[int, dict[str, Any]] = {}
ACTIVE_DYNAMIC_BOTS: dict[str, threading.Thread] = {}
STATE_LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="streamly")
SHUTDOWN = threading.Event()

@app.route('/')
def home():
    return "✨ 7G Main Bot & Dynamic Bot Manager Online & Running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def log(message: str, *args: Any) -> None:
    LOG.info(message, *args)

def format_bytes(value: int | float) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"

def escape(value: Any) -> str:
    return html.escape(str(value), quote=False)

# ----------------- DATABASE MANAGEMENT ----------------- #
def load_data(filepath):
    if not os.path.exists(filepath):
        return {} if "users" in filepath or "config" in filepath else []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if "users" in filepath or "config" in filepath else []

def save_data(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Data Save Error: {e}")

def get_config():
    config = load_data(CONFIG_FILE)
    if not isinstance(config, dict):
        config = {"maintenance": False}
        save_data(CONFIG_FILE, config)
    return config

def is_banned(user_id):
    banned_list = load_data(BANNED_FILE)
    if not isinstance(banned_list, list):
        banned_list = []
    return str(user_id) in [str(u) for u in banned_list]

def track_user_activity(user, action_type, text_data="", referred_by=None):
    user_id = str(user.id)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    users_db = load_data(USER_FILE)
    if not isinstance(users_db, dict):
        users_db = {}
    
    if user_id not in users_db:
        users_db[user_id] = {
            "first_name": user.first_name or "Unknown",
            "username": f"@{user.username}" if user.username else "No Username",
            "language_code": user.language_code or "N/A",
            "first_seen": now_str,
            "last_seen": now_str,
            "msg_count": 1,
            "downloads_count": 1 if "Download" in action_type else 0,
            "download_links": [text_data] if "Download" in action_type and text_data else [],
            "referred_by": referred_by,
            "referrals": [],
            "points": 0
        }
    else:
        users_db[user_id]["last_seen"] = now_str
        users_db[user_id]["msg_count"] = users_db[user_id].get("msg_count", 0) + 1
        if user.first_name:
            users_db[user_id]["first_name"] = user.first_name
        if user.username:
            users_db[user_id]["username"] = f"@{user.username}"
        
        if "Download" in action_type:
            users_db[user_id]["downloads_count"] = users_db[user_id].get("downloads_count", 0) + 1
            if text_data:
                if "download_links" not in users_db[user_id]:
                    users_db[user_id]["download_links"] = []
                users_db[user_id]["download_links"].append(text_data)

    save_data(USER_FILE, users_db)
    send_admin_alert(user, action_type, text_data, users_db[user_id])

def send_admin_alert(user, action_type, text_data, user_info):
    try:
        alert_msg = (
            f"🚨 *New Bot Activity Alert!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Name:* {user_info['first_name']}\n"
            f"🔗 *Username:* {user_info['username']}\n"
            f"🆔 *User ID:* `{user.id}`\n"
            f"💬 *Total Messages:* `{user_info['msg_count']}`\n"
            f"📥 *Total Downloads:* `{user_info['downloads_count']}`\n"
            f"⚡ *Action:* {action_type}\n"
            f"📌 *Data/Link:* {text_data}\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(ADMIN_ID, alert_msg, parse_mode="Markdown")
    except Exception as e:
        print(f"Admin Alert Error: {e}")

# ----------------- HTTP & DOWNLOAD ENGINES ----------------- #
def http_request(url: str, *, method: str = "GET", payload: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 35, max_bytes: int = 3 * 1024 * 1024) -> tuple[int, dict[str, str], bytes]:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    request = Request(url, data=payload, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            chunks: list[bytes] = []
            total = 0
            while total < max_bytes:
                chunk = response.read(min(64 * 1024, max_bytes - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            return response.status, dict(response.headers.items()), b"".join(chunks)
    except HTTPError as error:
        body = error.read(1024)
        raise RuntimeError(f"Remote HTTP {error.code}: {body.decode(errors='replace')[:180]}") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"Remote service unreachable: {error}") from error

def json_request(url: str, *, method: str = "GET", data: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 35) -> Any:
    body = json.dumps(data).encode() if data is not None else None
    request_headers = {"Content-Type": "application/json"} if data is not None else {}
    if headers:
        request_headers.update(headers)
    _, _, raw = http_request(url, method=method, payload=body, headers=request_headers, timeout=timeout)
    return json.loads(raw.decode("utf-8", errors="replace"))

def download_instagram(url):
    ydl_opts = {'format': 'best', 'quiet': True, 'no_warnings': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'url' in info:
                return info['url']
            elif 'entries' in info and len(info['entries']) > 0:
                return info['entries'][0]['url']
    except Exception:
        pass
    clean_url = url.split("?")[0]
    try:
        api_url = f"https://api.vkrdown.com/insta/?url={clean_url}"
        res = requests.get(api_url, timeout=10).json()
        if "data" in res and res["data"]:
            return res["data"][0].get("url")
    except Exception:
        pass
    return None

def _remote_url(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return None

def _media_links(value: Any) -> tuple[list[str], list[str]]:
    videos, audios = [], []
    if isinstance(value, dict):
        for key, nested in value.items():
            hint = key.lower()
            url = _remote_url(nested)
            if url:
                if any(w in hint for w in ("music", "audio", "mp3", "sound")):
                    audios.append(url)
                elif any(w in hint for w in ("play", "video", "mp4", "download", "hd", "url")) and not any(w in hint for w in ("cover", "avatar", "thumb")):
                    videos.append(url)
            nv, na = _media_links(nested)
            videos.extend(nv)
            audios.extend(na)
    elif isinstance(value, list):
        for item in value:
            nv, na = _media_links(item)
            videos.extend(nv)
            audios.extend(na)
    return list(dict.fromkeys(videos)), list(dict.fromkeys(audios))

def _resolve_tikwm(source_url: str) -> tuple[str, list[dict[str, Any]]]:
    endpoint = f"{TIKWM_ENDPOINT}?{urlencode({'url': source_url, 'hd': '1'})}"
    response = json_request(endpoint, timeout=45)
    if not isinstance(response, dict) or response.get("code") not in {0, "0", None}:
        raise RuntimeError("TikWM resolution failed")
    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("TikWM returned no data")
    title = str(data.get("title") or "TikTok video")
    video_urls, audio_urls = _media_links(data)
    preferred_video = [_remote_url(data.get(k)) for k in ("hdplay", "play", "wmplay") if _remote_url(data.get(k))]
    preferred_audio = [_remote_url(data.get(k)) for k in ("music", "music_url", "mp3", "audio") if _remote_url(data.get(k))]
    video_urls = list(dict.fromkeys(preferred_video + video_urls))
    
    options = []
    for idx, vurl in enumerate(video_urls[:3]):
        options.append({
            "url": vurl,
            "audio_url": preferred_audio[0] if preferred_audio else (audio_urls[0] if audio_urls else ""),
            "label": f"HD Quality {idx+1}" if idx == 0 else f"Standard Quality {idx+1}",
            "size": 0
        })
    return title, options

def _resolve_snaptik(source_url: str) -> tuple[str, list[dict[str, Any]]]:
    body = urlencode({"url": source_url}).encode()
    _, _, raw = http_request(
        SNAPTIK_ENDPOINT, method="POST", payload=body,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Referer": "https://snaptik.app/"},
        timeout=45
    )
    response = json.loads(raw.decode("utf-8", errors="replace"))
    if isinstance(response, dict) and response.get("success") is False:
        raise RuntimeError("SnapTik resolution failed")
    video_urls, audio_urls = _media_links(response)
    title = str(response.get("title") or "TikTok video")
    options = []
    for idx, vurl in enumerate(video_urls[:3]):
        options.append({
            "url": vurl,
            "audio_url": audio_urls[0] if audio_urls else "",
            "label": f"SnapTik Quality {idx+1}",
            "size": 0
        })
    return title, options

def tiktok_info(source_url: str) -> tuple[str, list[dict[str, Any]]]:
    for resolver in (_resolve_tikwm, _resolve_snaptik):
        try:
            return resolver(source_url)
        except Exception:
            continue
    raise RuntimeError("All TikTok download APIs failed to resolve this URL.")

# ----------------- AI ASSISTANT FUNCTIONS ----------------- #
def ai_request(message: str) -> Any:
    if not META_AI_KEY:
        raise RuntimeError("META_AI_API_KEY is not configured")
    return json_request(
        META_AI_ENDPOINT,
        method="POST",
        data={"api_key": META_AI_KEY, "message": message},
        headers={"Accept": "application/json"},
        timeout=75,
    )

def extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("response", "reply", "message", "text", "content", "answer", "output"):
            if key in value:
                result = extract_text(value[key])
                if result:
                    return result
        for nested in value.values():
            result = extract_text(nested)
            if result:
                return result
    if isinstance(value, list):
        return "\n".join(result for item in value if (result := extract_text(item)))
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
                except (ValueError, IndexError):
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
    cleaned = re.sub(r"\s+", " ", prompt).strip()[:700]
    return f"{IMAGE_FALLBACK_ENDPOINT}{quote(cleaned, safe='')}?width=1024&height=1024&nologo=true"

def send_ai_response(chat_id: int, prompt: str, status_id: int) -> None:
    try:
        response = ai_request(prompt)
        image_url, image_bytes = extract_image(response)
        text = extract_text(response).strip()
        image_request = prompt.lstrip().lower().startswith("/image")
        if image_request and not image_url and not image_bytes:
            image_url = fallback_image_url(prompt.lstrip()[len("/image") :].strip())
        if image_url:
            bot.send_photo(chat_id, image_url, caption="Generated image")
        elif image_bytes:
            bot.send_photo(chat_id, image_bytes, caption="Generated image")
        if image_request:
            bot.edit_message_text(f"<b>Image ready</b>\n\n{escape(text[:700] or 'ছবি তৈরি করা হয়েছে।')}", chat_id, status_id, parse_mode="HTML")
            return
        bot.edit_message_text(f"<b>AI assistant</b>\n\n{escape(text[:MAX_TEXT_LENGTH] or 'Response পাওয়া গেছে।')}", chat_id, status_id, parse_mode="HTML")
    except Exception as error:
        log("AI request failed: %s", error)
        bot.edit_message_text("<b>AI assistant</b>\n\nএই মুহূর্তে উত্তর আনা যায়নি। কিছুক্ষণ পর আবার চেষ্টা করুন।", chat_id, status_id, parse_mode="HTML")

# ----------------- DYNAMIC BOT SPAWNER (CREATE BOT FEATURE) ----------------- #
def run_dynamic_bot(new_token: str):
    try:
        dyn_bot = telebot.TeleBot(new_token)

        @dyn_bot.message_handler(commands=['start'])
        def dyn_start(message):
            dyn_bot.reply_to(message, "✨ *Welcome to your Custom 7G Bot!*\n\nPowered by 7G Ultimate Bot Engine (Credit: Amaz Uddin Abir).", parse_mode="Markdown")

        @dyn_bot.message_handler(func=lambda msg: True)
        def dyn_echo(message):
            dyn_bot.reply_to(message, f"🤖 *Echo from Custom Bot:*\n{message.text}\n\n_Powered by 7G Ultimate Bot._", parse_mode="Markdown")

        log("Dynamic Bot started successfully with token prefix: %s...", new_token[:10])
        dyn_bot.infinity_polling(skip_pending=True)
    except Exception as e:
        log("Dynamic Bot Error with token %s: %s", new_token[:10], e)

# ----------------- BOT COMMANDS & ADMIN MENUS ----------------- #

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "❌ *You are banned from using this bot!*", parse_mode="Markdown")
        return

    config = get_config()
    if config.get("maintenance", False) and message.chat.id != ADMIN_ID:
        bot.reply_to(message, "🛠️ *Bot is under maintenance! Please try again later.*", parse_mode="Markdown")
        return

    track_user_activity(message.from_user, "Start Command / New Visitor", message.text)

    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        telebot.types.KeyboardButton("📊 My Stats"),
        telebot.types.KeyboardButton("🔗 Referral Link"),
        telebot.types.KeyboardButton("✨ Create Bot")
    )

    welcome_text = (
        "✨🔥 *Welcome to 7G Ultimate Bot!* 🔥✨\n\n"
        "📥 *Instagram & TikTok:* Send any link for instant HD download!\n"
        "🤖 *AI Assistant & Image Generation (/ai, /image)*\n"
        "✨ *Create Bot:* Spin up your own bot instantly using the menu below!\n\n"
        "👇 *Use the bottom menu for quick options!*"
    )
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['createbot'])
def create_bot_command(message):
    if is_banned(message.chat.id):
        return
    CHAT_MODES[message.chat.id] = "awaiting_token"
    bot.reply_to(message, "🤖 *Create Your Own Bot*\n\nPlease send your new Telegram Bot Token (from @BotFather) to launch it instantly!", parse_mode="Markdown")

@bot.message_handler(commands=['mystats'])
def user_stats(message):
    if is_banned(message.chat.id):
        return
    users_db = load_data(USER_FILE)
    user_info = users_db.get(str(message.chat.id), {})
    
    msgs = user_info.get("msg_count", 0)
    downloads = user_info.get("downloads_count", 0)
    first_seen = user_info.get("first_seen", "N/A")
    
    stats_msg = (
        f"📊 *Your Personal Bot Statistics* 🌟\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 *Joined Date:* `{first_seen}`\n"
        f"💬 *Total Messages Sent:* `{msgs}`\n"
        f"📥 *Total Videos Downloaded:* `{downloads}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ *Thanks for using 7G Bot!* ❤️"
    )
    bot.reply_to(message, stats_msg, parse_mode="Markdown")

@bot.message_handler(commands=['stats', 'users'])
def show_stats(message):
    if message.chat.id != ADMIN_ID:
        return

    users_db = load_data(USER_FILE)
    total_users = len(users_db)
    total_downloads = sum(u.get("downloads_count", 0) for u in users_db.values())

    stats_text = (
        f"📊 *Admin Dashboard Statistics*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Total Users:* `{total_users}`\n"
        f"📥 *Total Downloads:* `{total_downloads}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 *All Users & Download History:* \n"
    )

    for uid, info in users_db.items():
        name = info.get('first_name', 'Unknown')
        uname = info.get('username', 'No Username')
        dl_count = info.get('downloads_count', 0)
        links = info.get('download_links', [])
        
        stats_text += f"\n👤 *{escape(name)}* ({escape(uname)})\n🆔 ID: `{uid}`\n📥 Downlo
