"""
=============================================================================
7G ULTIMATE TELEGRAM BOT (REFACTORED & ENHANCED PRODUCTION VERSION)
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
BOT_TOKEN = os.getenv("BOT_TOKEN", "7678905793:AAHG-u-pezwx3Cj-EF7koKwYZXDSZ55KENs").strip()
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
TELEGRAM_CHUNK_LIMIT = 3900

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

# ----------------- DATABASE MANAGEMENT ----------------- #
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

# ----------------- HTTP REQUEST HELPERS ----------------- #
def http_request(url: str, *, method: str = "GET", payload: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 35, max_bytes: int = 3 * 1024 * 1024) -> tuple[int, dict[str, str], bytes]:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    req = Request(url, data=payload, headers=request_headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
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
        raise RuntimeError(f"HTTP {error.code}: {body.decode(errors='replace')[:180]}") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"Remote service unreachable: {error}") from error

def json_request(url: str, *, method: str = "GET", data: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 35) -> Any:
    body = json.dumps(data).encode() if data is not None else None
    request_headers = {"Content-Type": "application/json"} if data is not None else {}
    if headers:
        request_headers.update(headers)
    _, _, raw = http_request(url, method=method, payload=body, headers=request_headers, timeout=timeout)
    return json.loads(raw.decode("utf-8", errors="replace"))

# ----------------- DOWNLOAD ENGINES ----------------- #
def download_instagram(url: str) -> str | None:
    ydl_opts = {"format": "best", "quiet": True, "no_warnings": True, "simulate": True}
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
        log("Instagram yt-dlp extraction note: %s", e)

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
        raise RuntimeError("TikWM error")
    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("TikWM returned empty payload")
    title = str(data.get("title") or "TikTok Video")
    video_url = data.get("hdplay") or data.get("play") or data.get("wmplay")
    if not video_url:
        raise RuntimeError("TikWM did not contain a valid video link")
    return title, video_url

def download_tiktok(source_url: str) -> tuple[str, str]:
    try:
        return resolve_tiktok_tikwm(source_url)
    except Exception:
        pass
    
    ydl_opts = {"format": "best[ext=mp4]/best", "quiet": True, "no_warnings": True, "simulate": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(source_url, download=False)
        if info:
            return info.get("title") or "TikTok Video", info.get("url")
    raise RuntimeError("Unable to download this TikTok video.")

# ----------------- AI ASSISTANT ----------------- #
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
        is_image_cmd = prompt.lstrip().lower().startswith("/image")
        if is_image_cmd and not image_url and not image_bytes:
            clean_prompt = prompt.lstrip()[len("/image"):].strip()
            image_url = fallback_image_url(clean_prompt or "Creative futuristic art")
        
        if image_url:
            bot.send_photo(chat_id, image_url, caption="✨ *Generated by AI Assistant*", parse_mode="Markdown")
        elif image_bytes:
            bot.send_photo(chat_id, image_bytes, caption="✨ *Generated by AI Assistant*", parse_mode="Markdown")
        
        if is_image_cmd:
            try:
                bot.delete_message(chat_id, status_id)
            except Exception:
                bot.edit_message_text("🖼️ *Your image has been generated above!*", chat_id, status_id, parse_mode="Markdown")
            return

        final_text = text if text else "I have processed your request."
        if len(final_text) > TELEGRAM_CHUNK_LIMIT:
            try:
                bot.delete_message(chat_id, status_id)
            except Exception:
                pass
            chunk_and_send(chat_id, f"🤖 *AI Assistant Response:*\n\n{final_text}", parse_mode="Markdown")
        else:
            bot.edit_message_text(f"🤖 *AI Assistant:*\n\n{final_text}", chat_id, status_id)
    except Exception as error:
        log_error("AI Assistant processing error: %s", error)
        try:
            bot.edit_message_text("⚠️ *Sorry, the AI Assistant is temporarily unavailable.*", chat_id, status_id, parse_mode="Markdown")
        except Exception:
            pass

# ----------------- TELEGRAM BOT COMMAND HANDLERS ----------------- #
@bot.message_handler(commands=["start"])
def handle_start(message: telebot.types.Message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "❌ *You are banned from using this bot!*", parse_mode="Markdown")
        return

    config = get_config()
    if config.get("maintenance", False) and message.chat.id != ADMIN_ID:
        bot.reply_to(message, "⚠️ Notice: The bot is currently undergoing system security updates and maintenance. It is temporarily unavailable. Please try again later!")
        return

    referred_by = None
    args = message.text.split()
    if len(args) > 1 and args[1].isdigit() and args[1] != str(message.chat.id):
        referred_by = args[1]

    track_user_activity(message.from_user, "Start Command / New Visitor", message.text, referred_by=referred_by)

    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        telebot.types.KeyboardButton("📊 My Stats"),
        telebot.types.KeyboardButton("🔗 Referral Link"),
        telebot.types.KeyboardButton("✨ Features Guide"),
    )

    welcome_text = (
        "✨🔥 *Welcome to 7G Ultimate Bot!* 🔥✨\n\n"
        "📥 *Instagram & TikTok:* Send any video link for instant HD download!\n"
        "🤖 *AI Assistant:* Ask any question or use `/ai <query>`\n\n"
        "👇 *Use the bottom menu for quick access!*"
    )
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=["mystats"])
def handle_my_stats(message: telebot.types.Message):
    if is_banned(message.chat.id):
        return
    users_db = load_data(USER_FILE)
    user_info = users_db.get(str(message.chat.id), {})

    msgs = user_info.get("msg_count", 0)
    downloads = user_info.get("downloads_count", 0)
    first_seen = user_info.get("first_seen", "N/A")
    referrals_count = len(user_info.get("referrals", []))

    stats_msg = (
        f"📊 *Your Personal Bot Statistics* 🌟\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 *Joined Date:* `{first_seen}`\n"
        f"💬 *Total Messages Sent:* `{msgs}`\n"
        f"📥 *Total Videos Downloaded:* `{downloads}`\n"
        f"👥 *Total Friends Invited:* `{referrals_count}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    bot.reply_to(message, stats_msg, parse_mode="Markdown")

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
        f"👥 *Total Users:* `{total_users}`\n"
        f"📥 *Total Downloads:* `{total_downloads}`\n"
        f"💬 *Total Messages:* `{total_messages}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    user_blocks: list[str] = [header]
    for index, (uid, info) in enumerate(users_db.items(), start=1):
        name = escape_markdown(info.get("first_name", "Unknown"))
        uname = escape_markdown(info.get("username", "No Username"))
        dl_count = info.get("downloads_count", 0)
        msg_count = info.get("msg_count", 0)
        first_seen = info.get("first_seen", "N/A")
        
        messages_list = info.get("messages", [])
        serialized_msgs = "\n".join([f"   {i}. \"{escape_markdown(m[:100])}\"" for i, m in enumerate(messages_list, start=1)]) if messages_list else "    _(No standalone messages)_"

        links_list = info.get("download_links", [])
        serialized_links = "\n".join([f"   {i}. `{escape_markdown(l)}`" for i, l in enumerate(links_list, start=1)]) if links_list else "    _(No links yet)_"

        user_block = (
            f"👤 *User #{index}:* {name} ({uname})\n"
            f"🆔 *ID:* `{uid}` | 📅 *Joined:* `{first_seen}`\n"
            f"📥 *Downloads:* `{dl_count}` | 💬 *Msgs:* `{msg_count}`\n"
            f"💬 *Messages List:*\n{serialized_msgs}\n"
            f"🔗 *Links List:*\n{serialized_links}\n"
            f"──────────────────────────────\n"
        )
        user_blocks.append(user_block)

    chunk_and_send(message.chat.id, "\n".join(user_blocks), parse_mode="Markdown")

@bot.message_handler(commands=["userinfo"])
def handle_user_info(message: telebot.types.Message):
    if message.chat.id != ADMIN_ID:
        return
    tokens = message.text.split()
    if len(tokens) < 2:
        bot.reply_to(message, "⚠️ *Usage:* `/userinfo <user_id>`", parse_mode="Markdown")
        return
    target_id = tokens[1].strip()
    users_db = load_data(USER_FILE)
    if not isinstance(users_db, dict) or target_id not in users_db:
        bot.reply_to(message, f"❌ *User ID `{target_id}` not found.*", parse_mode="Markdown")
        return

    info = users_db[target_id]
    msgs_list = info.get("messages", [])
    links_list = info.get("download_links", [])
    
    serialized_msgs = "\n".join([f"   {i}. \"{escape_markdown(m)}\"" for i, m in enumerate(msgs_list, start=1)]) if msgs_list else "  _(No messages)_"
    serialized_links = "\n".join([f"   {i}. `{escape_markdown(l)}`" for i, l in enumerate(links_list, start=1)]) if links_list else "  _(No links)_"

    details = (
        f"🔍 *DETAILED USER PROFILE*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Name: {escape_markdown(info.get('first_name'))}\n"
        f"🆔 ID: `{target_id}`\n"
        f"💬 Messages List:\n{serialized_msgs}\n\n"
        f"🔗 Links List:\n{serialized_links}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    chunk_and_send(message.chat.id, details, parse_mode="Markdown")

@bot.message_handler(commands=["maintenance"])
def handle_maintenance(message: telebot.types.Message):
    if message.chat.id != ADMIN_ID:
        return
    config = get_config()
    new_status = not config.get("maintenance", False)
    config["maintenance"] = new_status
    save_data(CONFIG_FILE, config)
    
    if new_status:
        bot.reply_to(message, "🛠️ *Maintenance mode turned ON! Broadcasting notice...*", parse_mode="Markdown")
        EXECUTOR.submit(broadcast_maintenance_notice, message.chat.id)
    else:
        bot.reply_to(message, "✅ *Maintenance mode turned OFF!*", parse_mode="Markdown")

def broadcast_maintenance_notice(admin_chat_id: int) -> None:
    notice_text = "⚠️ Notice: The bot is currently undergoing system security updates and maintenance. It is temporarily unavailable. Please try again later!"
    users_db = load_data(USER_FILE)
    if not isinstance(users_db, dict):
        return
    sent = 0
    for uid in users_db.keys():
        if str(uid) == str(ADMIN_ID):
            continue
        try:
            bot.send_message(uid, notice_text)
            sent += 1
            time.sleep(0.05)
        except Exception:
            pass
    try:
        bot.send_message(admin_chat_id, f"📢 *Maintenance Broadcast Delivered to:* `{sent}` users", parse_mode="Markdown")
    except Exception:
        pass

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
    if target_id not in banned_list:
        banned_list.append(target_id)
        save_data(BANNED_FILE, banned_list)
        try:
            bot.send_message(target_id, "❌ Notice: Your access to this bot has been banned due to suspicious or unwanted activity.")
        except Exception:
            pass
        bot.reply_to(message, f"✅ *User ID `{target_id}` banned successfully.*", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"⚠️ *User already banned.*", parse_mode="Markdown")

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
    if isinstance(banned_list, list) and target_id in banned_list:
        banned_list.remove(target_id)
        save_data(BANNED_FILE, banned_list)
        try:
            bot.send_message(target_id, "✅ Notice: Your account has been unbanned. You can now use the bot again.")
        except Exception:
            pass
        bot.reply_to(message, f"✅ *User ID `{target_id}` unbanned successfully.*", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"⚠️ *User not found in ban list.*", parse_mode="Markdown")

@bot.message_handler(commands=["broadcast"])
def handle_broadcast(message: telebot.types.Message):
    if message.chat.id != ADMIN_ID:
        return
    announcement = message.text[len("/broadcast"):].strip()
    if not announcement:
        bot.reply_to(message, "⚠️ *Usage:* `/broadcast <message>`", parse_mode="Markdown")
        return
    users_db = load_data(USER_FILE)
    if not isinstance(users_db, dict) or not users_db:
        bot.reply_to(message, "❌ *No users found.*", parse_mode="Markdown")
        return
    bot.reply_to(message, f"🚀 *Broadcasting to {len(users_db)} users...*", parse_mode="Markdown")
    EXECUTOR.submit(execute_broadcast, message.chat.id, announcement)

def execute_broadcast(admin_chat_id: int, content: str) -> None:
    users_db = load_data(USER_FILE)
    if not isinstance(users_db, dict):
        return
    formatted_msg = f"📢 *Admin Announcement:*\n\n{content}"
    sent = 0
    failed = 0
    for uid in users_db.keys():
        try:
            bot.send_message(uid, formatted_msg, parse_mode="Markdown")
            sent += 1
            time.sleep(0.05)
        except Exception:
            failed += 1
    try:
        bot.send_message(admin_chat_id, f"✅ *Broadcast Finished!*\n🟢 Sent: `{sent}`\n🔴 Failed: `{failed}`", parse_mode="Markdown")
    except Exception:
        pass

# ----------------- MESSAGE & LINK PROCESSOR ----------------- #
@bot.message_handler(func=lambda message: True)
def process_incoming_message(message: telebot.types.Message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "❌ *Notice: Your access to this bot is currently banned.*", parse_mode="Markdown")
        return

    config = get_config()
    if config.get("maintenance", False) and message.chat.id != ADMIN_ID:
        bot.reply_to(message, "⚠️ Notice: The bot is currently undergoing system security updates and maintenance. It is temporarily unavailable. Please try again later!")
        return

    text = (message.text or "").strip()

    if text == "📊 My Stats":
        handle_my_stats(message)
        return
    elif text == "🔗 Referral Link":
        try:
            bot_username = bot.get_me().username
            ref_link = f"https://t.me/{bot_username}?start={message.chat.id}"
            bot.reply_to(message, f"👥 *Your Personal Referral Link:*\n`{ref_link}`", parse_mode="Markdown")
        except Exception:
            bot.reply_to(message, f"🔗 *Referral code:* `{message.chat.id}`")
        return
    elif text == "✨ Features Guide":
        help_text = "📌 *7G Bot Features:* Send any Instagram or TikTok link for instant download, or type anything to chat with AI."
        bot.reply_to(message, help_text, parse_mode="Markdown")
        return

    if text.startswith("/ai"):
        prompt = text[len("/ai"):].strip()
        if prompt:
            track_user_activity(message.from_user, "AI Query", text)
            status_msg = bot.reply_to(message, "💭 *Thinking...*", parse_mode="Markdown")
            EXECUTOR.submit(send_ai_response, message.chat.id, prompt, status_msg.message_id)
        else:
            bot.reply_to(message, "⚠️ *Usage:* `/ai <question>`", parse_mode="Markdown")
        return

    if text.startswith("/image"):
        prompt = text[len("/image"):].strip()
        if prompt:
            track_user_activity(message.from_user, "AI Image Request", text)
            status_msg = bot.reply_to(message, "🎨 *Generating image...*", parse_mode="Markdown")
            EXECUTOR.submit(send_ai_response, message.chat.id, f"/image {prompt}", status_msg.message_id)
        else:
            bot.reply_to(message, "⚠️ *Usage:* `/image <prompt>`", parse_mode="Markdown")
        return

    if "instagram.com" in text.lower():
        track_user_activity(message.from_user, "Instagram Download", text)
        status_msg = bot.reply_to(message, "⏳ *Downloading Instagram media...*", parse_mode="Markdown")
        EXECUTOR.submit(handle_instagram_download_task, message, text, status_msg.message_id)
        return

    if "tiktok.com" in text.lower() or "vt.tiktok.com" in text.lower():
        track_user_activity(message.from_user, "TikTok Download", text)
        status_msg = bot.reply_to(message, "⏳ *Downloading TikTok video...*", parse_mode="Markdown")
        EXECUTOR.submit(handle_tiktok_download_task, message, text, status_msg.message_id)
        return

    track_user_activity(message.from_user, "General Chat", text)
    status_msg = bot.reply_to(message, "💭 *Thinking...*", parse_mode="Markdown")
    EXECUTOR.submit(send_ai_response, message.chat.id, text, status_msg.message_id)

def handle_instagram_download_task(message: telebot.types.Message, url: str, status_msg_id: int) -> None:
    try:
        video_url = download_instagram(url)
        if video_url:
            bot.send_video(message.chat.id, video_url, caption="📥 *Downloaded via 7G Bot*", parse_mode="Markdown")
            try:
                bot.delete_message(message.chat.id, status_msg_id)
            except Exception:
                pass
        else:
            bot.edit_message_text("❌ *Failed to extract Instagram media.*", message.chat.id, status_msg_id, parse_mode="Markdown")
    except Exception as e:
        log_error("Instagram delivery error: %s", e)
        bot.edit_message_text("❌ *Download failed.*", message.chat.id, status_msg_id, parse_mode="Markdown")

def handle_tiktok_download_task(message: telebot.types.Message, url: str, status_msg_id: int) -> None:
    try:
        title, video_url = download_tiktok(url)
        clean_title = escape(title[:250])
        caption = f"📥 <b>{clean_title}</b>\n\n⚡ <i>Downloaded via 7G Bot</i>"
        bot.send_video(message.chat.id, video_url, caption=caption, parse_mode="HTML")
        try:
            bot.delete_message(message.chat.id, status_msg_id)
        except Exception:
            pass
    except Exception as e:
        log
