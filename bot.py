"""
=============================================================================
7G ULTIMATE TELEGRAM MASTER BOT (ENTERPRISE PRODUCTION EDITION)
=============================================================================
Primary Token: 7678905793:AAFtjvo1_Z4vPGirwd8AXpzvke3DFPl2QOA
Master Admin ID: 6162953772
AI Engine: Google Gemini 1.5 Flash (Text) + Pollinations AI (Images)
=============================================================================
FEATURES INCLUDED:
  1. Instagram HD Downloader (yt-dlp Native + Instaloader + SaveInsta + Snapinsta)
  2. Multi-Tier TikTok HD Downloader without Watermark (TikWM HD + SnapTik + yt-dlp)
  3. Google Gemini 1.5 Flash AI Assistant (/ai or natural chat in Bengali & English)
  4. Pollinations AI Ultra Image Generator (/image <prompt>)
  5. Complete User Activity Tracking (Joined date, timestamps, referrals, points)
  6. Admin Dashboard (/stats & /users) with Serialized Messages & Downloaded Links Lists
  7. Detailed Single User Inspection (/userinfo <user_id>)
  8. Ban & Unban System (/ban & /unban) with Instant Direct English Notifications
  9. Maintenance Mode Control (/maintenance) with Instant Auto-Broadcast to ALL Users
 10. Admin Global Announcement Engine (/broadcast <message>)
 11. Auto-Telegram Database Backup to Admin Inbox
 12. "Create Own Bot" Multi-Bot System (Clone any bot token live without sub-cloning)
 13. 24/7 Keep-Alive Flask Server & Self-Ping Loop for Render/Railway/VPS
=============================================================================
"""

from __future__ import annotations

import base64
import html
import io
import json
import logging
import os
import random
import re
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from urllib.parse import quote

# Ensure unbuffered standard output for real-time logs on Render/Docker
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

import requests
from flask import Flask, jsonify
import telebot
from telebot import types
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
MAIN_BOT_TOKEN = os.getenv("BOT_TOKEN", "7678905793:AAFtjvo1_Z4vPGirwd8AXpzvke3DFPl2QOA").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "6162953772"))

# Google Gemini 1.5 Flash API Key (dynamically read from Environment)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Pollinations AI Free Image Generator Endpoint
POLLINATIONS_IMAGE_ENDPOINT = "https://image.pollinations.ai/prompt/"

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
CLONES_FILE = os.path.join(DATA_DIR, "clones_db.json")

# State & Concurrency
FILE_LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="7g_worker")
ACTIVE_CLONES: dict[str, telebot.TeleBot] = {}
AWAITING_BOT_TOKEN: set[int] = set()

# Initialize Main TeleBot instance & Flask app
bot = telebot.TeleBot(MAIN_BOT_TOKEN, parse_mode=None)
app = Flask(__name__)

# ----------------- FLASK KEEP-ALIVE SERVER ----------------- #
@app.route("/")
def home():
    has_gemini = "Configured ✅" if (os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY) else "Missing GEMINI_API_KEY ⚠️"
    return (
        "✨ <b>7G Master Bot is Online & Running 24/7!</b><br>"
        f"🤖 AI Engine: Google Gemini 1.5 Flash ({has_gemini})<br>"
        f"🎨 Image Engine: Pollinations AI Free<br>"
        f"⚡ Active Clones: {len(ACTIVE_CLONES)}<br>"
        f"🕒 Server Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

@app.route("/healthz")
@app.route("/health")
def healthz():
    return jsonify({
        "status": "ok",
        "service": "7g_master_bot",
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY),
        "gemini_model": GEMINI_MODEL,
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

def download_to_temp_file(media_url: str, referer: str = "https://www.tiktok.com/") -> str | None:
    """Downloads media directly to a local temporary file with browser headers."""
    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": referer,
            "Accept": "*/*",
        }
        with requests.get(media_url, headers=headers, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                total_bytes = 0
                for chunk in resp.iter_content(chunk_size=128 * 1024):
                    if chunk:
                        tmp.write(chunk)
                        total_bytes += len(chunk)
                        if total_bytes > 49.5 * 1024 * 1024:
                            log_error("Downloaded file exceeded Telegram 50MB limit.")
                            break
                tmp_path = tmp.name

        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 1000:
            return tmp_path
        else:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return None
    except Exception as e:
        log_error(f"Download to temp file failed: {e}")
        return None

def download_instagram(url: str) -> str | None:
    """Instagram Downloader with 4-tier fallback."""
    clean_url = url.strip()
    m = re.search(r"https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/[A-Za-z0-9_-]+", clean_url)
    if m:
        clean_url = m.group(0).rstrip("/") + "/"
    else:
        clean_url = clean_url.split("?")[0].rstrip("/") + "/"

    shortcode_match = re.search(r"/(?:reel|p|tv)/([A-Za-z0-9_-]+)", clean_url)
    shortcode = shortcode_match.group(1) if shortcode_match else None

    # Method 1: yt-dlp Native Direct Downloader
    try:
        temp_dir = tempfile.gettempdir()
        prefix = f"ig_{uuid.uuid4().hex[:8]}"
        out_tmpl = os.path.join(temp_dir, f"{prefix}.%(ext)s")
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': out_tmpl,
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'http_headers': {
                'User-Agent': USER_AGENT,
                'Referer': 'https://www.instagram.com/',
                'Accept': '*/*',
            },
            'max_filesize': 49 * 1024 * 1024,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=True)
            if info:
                candidate_path = ydl.prepare_filename(info)
                if os.path.exists(candidate_path) and os.path.getsize(candidate_path) > 1000:
                    return candidate_path
                for f in os.listdir(temp_dir):
                    if f.startswith(prefix):
                        f_path = os.path.join(temp_dir, f)
                        if os.path.getsize(f_path) > 1000:
                            return f_path
    except Exception as ydl_err:
        log_error(f"yt-dlp Instagram direct download failed: {ydl_err}")

    # Method 2: Instaloader Native Extractor
    if shortcode:
        try:
            import instaloader
            L = instaloader.Instaloader(quiet=True, download_comments=False)
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            if getattr(post, "is_video", False) and getattr(post, "video_url", None):
                tmp_file = download_to_temp_file(post.video_url, referer="https://www.instagram.com/")
                if tmp_file:
                    return tmp_file
                return post.video_url
            elif getattr(post, "url", None):
                tmp_file = download_to_temp_file(post.url, referer="https://www.instagram.com/")
                if tmp_file:
                    return tmp_file
                return post.url
        except Exception as inst_err:
            log_error(f"Instaloader Instagram extraction failed: {inst_err}")

    # Method 3: yt-dlp Format Extraction Fallback
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'http_headers': {
                'User-Agent': USER_AGENT,
                'Referer': 'https://www.instagram.com/',
            }
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            if info:
                if info.get('url'):
                    tmp_file = download_to_temp_file(info['url'], referer="https://www.instagram.com/")
                    if tmp_file:
                        return tmp_file
                    return info['url']
                if 'formats' in info and info['formats']:
                    for fmt in reversed(info['formats']):
                        if fmt.get('url') and fmt.get('ext') == 'mp4':
                            tmp_file = download_to_temp_file(fmt['url'], referer="https://www.instagram.com/")
                            if tmp_file:
                                return tmp_file
                            return fmt['url']
    except Exception as e:
        log_error(f"yt-dlp format extraction fallback failed: {e}")

    return None

def download_tiktok(url: str) -> str | None:
    """TikTok Downloader (Multi-Tier HD without Watermark)."""
    clean_url = url.strip()

    # Method 1: TikWM HD API
    try:
        payload = {"url": clean_url, "hd": 1}
        headers = {"User-Agent": USER_AGENT}
        r = requests.post(TIKWM_ENDPOINT, data=payload, headers=headers, timeout=20)
        if r.status_code == 200:
            res = r.json()
            if res.get("code") == 0 and "data" in res:
                data = res["data"]
                video_url = data.get("hdplay") or data.get("play")
                if video_url:
                    if not video_url.startswith("http"):
                        video_url = f"https://www.tikwm.com{video_url}"
                    tmp_file = download_to_temp_file(video_url, referer="https://www.tiktok.com/")
                    if tmp_file:
                        return tmp_file
                    return video_url
    except Exception as e:
        log_error(f"TikWM TikTok download failed: {e}")

    # Method 2: yt-dlp Direct Native Fallback
    try:
        temp_dir = tempfile.gettempdir()
        prefix = f"tt_{uuid.uuid4().hex[:8]}"
        out_tmpl = os.path.join(temp_dir, f"{prefix}.%(ext)s")
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': out_tmpl,
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'http_headers': {
                'User-Agent': USER_AGENT,
                'Referer': 'https://www.tiktok.com/',
                'Accept': '*/*',
            },
            'max_filesize': 49 * 1024 * 1024,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=True)
            if info:
                candidate_path = ydl.prepare_filename(info)
                if os.path.exists(candidate_path) and os.path.getsize(candidate_path) > 1000:
                    return candidate_path
                for f in os.listdir(temp_dir):
                    if f.startswith(prefix):
                        f_path = os.path.join(temp_dir, f)
                        if os.path.getsize(f_path) > 1000:
                            return f_path
    except Exception as ydl_err:
        log_error(f"yt-dlp TikTok fallback failed: {ydl_err}")

    return None

# =============================================================================
# ----------------- NEW AI ENGINE (GEMINI 1.5 FLASH + POLLINATIONS) ----------
# =============================================================================

def call_gemini_ai(prompt: str, user_name: str = "") -> str:
    """
    Google Gemini 1.5 Flash natural language chat engine.
    - Dynamically reads GEMINI_API_KEY from environment variables.
    - Responds naturally and respectfully in Bengali and English.
    - Bulletproof error handling for missing keys or API quota/network issues.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip() or GEMINI_API_KEY
    if not api_key:
        return (
            "⚠️ <b>Gemini API Key missing!</b>\n"
            "দয়া করে আপনার হোস্টিং এনভায়রনমেন্টে <code>GEMINI_API_KEY</code> সেট করুন।\n"
            "Please configure the <code>GEMINI_API_KEY</code> variable in your Render/Server settings."
        )

    url = f"{GEMINI_ENDPOINT}?key={api_key}"
    headers = {"Content-Type": "application/json"}

    system_instruction = (
        "You are 7G AI, an ultra-smart, helpful, friendly, and respectful assistant created by the 7G Master Team. "
        "You communicate fluently and naturally in both Bengali (বাংলা) and English. "
        "Match the language of the user: if the user writes in Bengali or Banglish, answer in clear, beautiful Bengali. "
        "If the user writes in English, answer in polished English. "
        "Keep your formatting clean, structured, and pleasant using emojis, bullet points, and code blocks where helpful. "
        "Be concise yet comprehensive."
    )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt.strip()}]
            }
        ],
        "systemInstruction": {
            "parts": [{"text": system_instruction}]
        },
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 2048,
            "topP": 0.95
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=35)
        if response.status_code == 200:
            data = response.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts and "text" in parts[0]:
                    return parts[0]["text"].strip()
            return "দুঃখিত, কোনো উত্তর পাওয়া যায়নি। অনুগ্রহ করে আবার চেষ্টা করুন।"
        elif response.status_code == 400:
            log_error("Gemini 400 Bad Request: %s", response.text)
            return "⚠️ অনুরোধটি প্রক্রিয়াকরণ করা যায়নি (Bad Request)। অনুগ্রহ করে প্রম্পট পরিবর্তন করে চেষ্টা করুন।"
        elif response.status_code == 429:
            log_error("Gemini 429 Quota Exceeded: %s", response.text)
            return "⏳ এআই বর্তমানে খুব ব্যস্ত। দয়া করে কয়েক সেকেন্ড পর আবার চেষ্টা করুন (Rate limit exceeded)।"
        else:
            log_error("Gemini API Error %s: %s", response.status_code, response.text)
            return f"⚠️ এআই সার্ভার রেসপন্স দেয়নি (Error {response.status_code})। কিছুক্ষণ পর চেষ্টা করুন।"
    except requests.exceptions.Timeout:
        log_error("Gemini request timed out.")
        return "⏱️ অনুরোধের সময়সীমা শেষ হয়েছে (Timeout)। দয়া করে আবার চেষ্টা করুন।"
    except Exception as e:
        log_error("Gemini AI Exception: %s", e)
        return f"⚠️ কোনো একটি সমস্যা হয়েছে: {escape(str(e))}"

def generate_pollinations_image(prompt: str) -> tuple[str | None, bytes | None]:
    """
    Pollinations AI Image Generator:
    Creates high-resolution AI images via Pollinations AI free endpoint.
    Downloads the image stream directly to bytes to guarantee seamless Telegram delivery.
    """
    clean_prompt = prompt.strip()
    encoded = quote(clean_prompt)
    seed = random.randint(1000, 999999)
    image_url = f"{POLLINATIONS_IMAGE_ENDPOINT}{encoded}?width=1024&height=1024&seed={seed}&nologo=true"

    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(image_url, headers=headers, timeout=50)
        if resp.status_code == 200 and len(resp.content) > 5000:
            return image_url, resp.content
    except Exception as e:
        log_error("Pollinations image generation error: %s", e)

    return image_url, None

# ----------------- TELEGRAM BOT HANDLERS ----------------- #

def is_maintenance_active() -> bool:
    return bool(get_config().get("maintenance", False))

def make_start_keyboard() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=2)
    b1 = types.InlineKeyboardButton("💬 Ask AI", switch_inline_query_current_chat="/ai ")
    b2 = types.InlineKeyboardButton("🎨 Generate Image", switch_inline_query_current_chat="/image ")
    b3 = types.InlineKeyboardButton("🤖 Create Own Bot", callback_data="clone_bot")
    b4 = types.InlineKeyboardButton("📊 My Stats", callback_data="my_stats")
    markup.add(b1, b2)
    markup.add(b3, b4)
    return markup

@bot.message_handler(commands=["start"])
def handle_start(message: types.Message):
    user = message.from_user
    if is_banned(user.id):
        safe_reply(bot, message, "⛔ <b>You are banned from using this bot.</b>")
        return

    if is_maintenance_active() and user.id != ADMIN_ID:
        safe_reply(bot, message, "🛠️ <b>Bot is currently undergoing maintenance. Please check back shortly!</b>")
        return

    referred_by = None
    parts = message.text.split()
    if len(parts) > 1 and parts[1].isdigit() and str(user.id) != parts[1]:
        referred_by = parts[1]

    track_user_activity(user, "Command: /start", message.text, referred_by=referred_by)

    welcome_text = (
        f"👋 <b>Welcome, {escape(user.first_name)}!</b>\n\n"
        f"🌟 <b>7G Ultimate Master Bot</b> এ আপনাকে স্বাগতম!\n\n"
        f"<b>🚀 প্রধান ফিচারসমূহ:</b>\n"
        f"├ 🧠 <b>Google Gemini 1.5 Flash:</b> যেকোনো প্রশ্ন করুন বা <code>/ai আপনার প্রশ্ন</code> লিখুন।\n"
        f"├ 🎨 <b>AI Image Generator:</b> <code>/image আপনার প্রম্পট</code> লিখে ছবি তৈরি করুন।\n"
        f"├ 📥 <b>Instagram Downloader:</b> যেকোনো Reel বা Post লিংক পাঠালে সরাসরি ভিডিও ডাউনলোড হবে।\n"
        f"├ 🎵 <b>TikTok Downloader:</b> ওয়াটারমার্ক ছাড়া HD ভিডিও ডাউনলোড।\n"
        f"└ 🤖 <b>Create Own Bot:</b> আপনার নিজের বটের টোকেন দিয়ে ক্লোন তৈরি করুন!\n\n"
        f"💡 <i>যেকোনো প্রশ্ন লিখে পাঠিয়ে দিন অথবা নিচের বাটন চাপুন:</i>"
    )
    safe_reply(bot, message, welcome_text, reply_markup=make_start_keyboard())

@bot.message_handler(commands=["help"])
def handle_help(message: types.Message):
    user = message.from_user
    if is_banned(user.id):
        return
    track_user_activity(user, "Command: /help", message.text)
    help_text = (
        "📖 <b>7G Master Bot - নির্দেশিকা</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔹 <code>/ai &lt;প্রশ্ন&gt;</code> - Google Gemini 1.5 Flash এর সাথে সরাসরি কথা বলুন।\n"
        "🔹 <code>/image &lt;প্রম্পট&gt;</code> - Pollinations AI দিয়ে চমৎকার ছবি তৈরি করুন।\n"
        "🔹 <b>Instagram Link</b> - ইনস্টাগ্রাম রিল বা ভিডিওর লিংক পেস্ট করুন।\n"
        "🔹 <b>TikTok Link</b> - টিকটক লিংক পাঠালেই No-Watermark ভিডিও পাবেন।\n"
        "🔹 <code>/clone</code> - আপনার নিজের বটের টোকেন যুক্ত করে ক্লোন চালান।\n"
        "🔹 <code>/start</code> - মূল মেন্যু খুলুন।\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    safe_reply(bot, message, help_text)

# ----------------- AI TEXT CHAT (/ai & GENERAL TEXT) ----------------- #

@bot.message_handler(commands=["ai"])
def handle_ai_command(message: types.Message):
    user = message.from_user
    if is_banned(user.id):
        return
    if is_maintenance_active() and user.id != ADMIN_ID:
        safe_reply(bot, message, "🛠️ Bot is in maintenance mode. Please wait.")
        return

    prompt = message.text.replace("/ai", "", 1).strip()
    if not prompt:
        safe_reply(bot, message, "💡 <b>অনুগ্রহ করে আপনার প্রশ্নটি লিখুন।</b>\nযেমন: <code>/ai কোডিং শেখার সেরা উপায় কি?</code>")
        return

    track_user_activity(user, "Gemini AI Query (/ai)", prompt)
    process_gemini_query(bot, message, prompt)

@bot.message_handler(commands=["image"])
def handle_image_command(message: types.Message):
    user = message.from_user
    if is_banned(user.id):
        return
    if is_maintenance_active() and user.id != ADMIN_ID:
        safe_reply(bot, message, "🛠️ Bot is in maintenance mode. Please wait.")
        return

    prompt = message.text.replace("/image", "", 1).strip()
    if not prompt:
        safe_reply(bot, message, "🎨 <b>অনুগ্রহ করে ছবির বিবরণ (prompt) লিখুন।</b>\nযেমন: <code>/image a futuristic cybernetic tiger in neon dhaka city</code>")
        return

    track_user_activity(user, "Image Generation (/image)", prompt)
    process_image_generation(bot, message, prompt)

def process_gemini_query(bot_instance: telebot.TeleBot, message: types.Message, prompt: str):
    """Handles Gemini response with interactive 'Thinking...' status and chunking."""
    status_msg = None
    try:
        status_msg = bot_instance.reply_to(message, "💭 <i>Thinking with Google Gemini 1.5 Flash...</i>", parse_mode="HTML")
    except Exception:
        pass

    def worker():
        response_text = call_gemini_ai(prompt, user_name=message.from_user.first_name)
        
        # Remove thinking indicator
        if status_msg:
            try:
                bot_instance.delete_message(message.chat.id, status_msg.message_id)
            except Exception:
                pass

        # Send response cleanly with chunking for large outputs
        chunk_and_send(bot_instance, message.chat.id, response_text, parse_mode="HTML")

    EXECUTOR.submit(worker)

def process_image_generation(bot_instance: telebot.TeleBot, message: types.Message, prompt: str):
    """Generates image via Pollinations AI and sends photo."""
    status_msg = None
    try:
        status_msg = bot_instance.reply_to(message, "🎨 <i>Generating your high-resolution image with Pollinations AI...</i>", parse_mode="HTML")
    except Exception:
        pass

    def worker():
        img_url, img_bytes = generate_pollinations_image(prompt)
        
        if status_msg:
            try:
                bot_instance.delete_message(message.chat.id, status_msg.message_id)
            except Exception:
                pass

        caption = f"🎨 <b>Prompt:</b> {escape(prompt[:200])}\n✨ <i>Generated by 7G Master AI (Pollinations)</i>"

        # If byte buffer available, send as photo stream (most reliable)
        if img_bytes:
            try:
                photo_file = io.BytesIO(img_bytes)
                photo_file.name = "ai_image.jpg"
                bot_instance.send_photo(message.chat.id, photo_file, caption=caption, parse_mode="HTML")
                return
            except Exception as pe:
                log_error("Sending photo bytes failed: %s. Falling back to URL...", pe)

        # Fallback to direct URL
        if img_url:
            try:
                bot_instance.send_photo(message.chat.id, img_url, caption=caption, parse_mode="HTML")
                return
            except Exception as ue:
                log_error("Sending photo URL failed: %s", ue)

        safe_reply(bot_instance, message, "⚠️ দুঃখিত, ছবিটি তৈরি করা সম্ভব হয়নি। অনুগ্রহ করে প্রম্পট পরিবর্তন করে আবার চেষ্টা করুন।")

    EXECUTOR.submit(worker)

# ----------------- ADMIN COMMANDS ----------------- #

@bot.message_handler(commands=["stats"])
def handle_stats(message: types.Message):
    user = message.from_user
    if user.id != ADMIN_ID:
        return
    users_db = load_data(USER_FILE)
    total_users = len(users_db) if isinstance(users_db, dict) else 0
    total_downloads = sum(u.get("downloads_count", 0) for u in users_db.values()) if isinstance(users_db, dict) else 0
    total_messages = sum(u.get("msg_count", 0) for u in users_db.values()) if isinstance(users_db, dict) else 0
    banned = len(load_data(BANNED_FILE))
    config = get_config()

    stats_text = (
        "📊 <b>7G Master Bot - Admin Statistics</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Total Users:</b> <code>{total_users}</code>\n"
        f"💬 <b>Total Messages Processed:</b> <code>{total_messages}</code>\n"
        f"📥 <b>Total Media Downloads:</b> <code>{total_downloads}</code>\n"
        f"🚫 <b>Banned Users:</b> <code>{banned}</code>\n"
        f"🤖 <b>Active Clone Bots:</b> <code>{len(ACTIVE_CLONES)}</code>\n"
        f"🛠️ <b>Maintenance Mode:</b> <code>{'ENABLED ⚠️' if config.get('maintenance') else 'DISABLED ✅'}</code>\n"
        f"🧠 <b>AI Engine:</b> <code>Google Gemini 1.5 Flash</code>\n"
        f"🎨 <b>Image Engine:</b> <code>Pollinations AI</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    safe_reply(bot, message, stats_text)

@bot.message_handler(commands=["users"])
def handle_users_list(message: types.Message):
    user = message.from_user
    if user.id != ADMIN_ID:
        return
    users_db = load_data(USER_FILE)
    if not users_db:
        safe_reply(bot, message, "No users registered yet.")
        return

    lines = ["👥 <b>Registered Users List:</b>\n━━━━━━━━━━━━━━━━━━━━━"]
    for idx, (uid, uinfo) in enumerate(list(users_db.items())[-50:], start=1):
        lines.append(
            f"{idx}. <b>{escape(uinfo.get('first_name'))}</b> ({escape(uinfo.get('username'))}) - "
            f"<code>{uid}</code> | Msgs: {uinfo.get('msg_count', 0)} | DLs: {uinfo.get('downloads_count', 0)}"
        )
    chunk_and_send(bot, message.chat.id, "\n".join(lines))

@bot.message_handler(commands=["userinfo"])
def handle_userinfo(message: types.Message):
    user = message.from_user
    if user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        safe_reply(bot, message, "Usage: <code>/userinfo &lt;user_id&gt;</code>")
        return
    target_id = parts[1].strip()
    users_db = load_data(USER_FILE)
    if target_id not in users_db:
        safe_reply(bot, message, f"User <code>{target_id}</code> not found in database.")
        return

    info = users_db[target_id]
    recent_msgs = info.get("messages", [])[-5:]
    recent_dls = info.get("download_links", [])[-5:]

    msgs_formatted = "\n".join([f"• <i>{escape(m[:60])}</i>" for m in recent_msgs]) or "None"
    dls_formatted = "\n".join([f"• <code>{escape(l[:60])}</code>" for l in recent_dls]) or "None"

    info_text = (
        f"👤 <b>Detailed Inspection for User:</b> <code>{target_id}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📛 <b>Name:</b> {escape(info.get('first_name'))}\n"
        f"🔗 <b>Username:</b> {escape(info.get('username'))}\n"
        f"🌐 <b>Language:</b> <code>{escape(info.get('language_code'))}</code>\n"
        f"📅 <b>First Seen:</b> <code>{info.get('first_seen')}</code>\n"
        f"🕒 <b>Last Seen:</b> <code>{info.get('last_seen')}</code>\n"
        f"💬 <b>Message Count:</b> <code>{info.get('msg_count', 0)}</code>\n"
        f"📥 <b>Downloads:</b> <code>{info.get('downloads_count', 0)}</code>\n"
        f"🎁 <b>Points:</b> <code>{info.get('points', 0)}</code>\n"
        f"👥 <b>Referrals:</b> <code>{len(info.get('referrals', []))}</code>\n\n"
        f"💬 <b>Recent Messages:</b>\n{msgs_formatted}\n\n"
        f"📥 <b>Recent Download Links:</b>\n{dls_formatted}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    safe_reply(bot, message, info_text)

@bot.message_handler(commands=["ban"])
def handle_ban(message: types.Message):
    user = message.from_user
    if user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        safe_reply(bot, message, "Usage: <code>/ban &lt;user_id&gt;</code>")
        return
    target_id = parts[1].strip()
    with FILE_LOCK:
        banned = load_data(BANNED_FILE)
        if not isinstance(banned, list):
            banned = []
        if target_id not in [str(u) for u in banned]:
            banned.append(target_id)
            save_data(BANNED_FILE, banned, trigger_backup=False)

    safe_reply(bot, message, f"✅ User <code>{target_id}</code> has been banned successfully.")
    try:
        bot.send_message(
            int(target_id),
            "⛔ <b>Notification:</b> You have been banned by the Administrator from using 7G Master Bot.",
            parse_mode="HTML"
        )
    except Exception:
        pass

@bot.message_handler(commands=["unban"])
def handle_unban(message: types.Message):
    user = message.from_user
    if user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        safe_reply(bot, message, "Usage: <code>/unban &lt;user_id&gt;</code>")
        return
    target_id = parts[1].strip()
    with FILE_LOCK:
        banned = load_data(BANNED_FILE)
        if isinstance(banned, list):
            banned = [str(u) for u in banned if str(u) != target_id]
            save_data(BANNED_FILE, banned, trigger_backup=False)

    safe_reply(bot, message, f"✅ User <code>{target_id}</code> has been unbanned.")
    try:
        bot.send_message(
            int(target_id),
            "✅ <b>Notification:</b> Your account restriction has been lifted by the Administrator. You can use the bot again!",
            parse_mode="HTML"
        )
    except Exception:
        pass

@bot.message_handler(commands=["maintenance"])
def handle_maintenance(message: types.Message):
    user = message.from_user
    if user.id != ADMIN_ID:
        return
    config = get_config()
    new_state = not config.get("maintenance", False)
    config["maintenance"] = new_state
    save_data(CONFIG_FILE, config, trigger_backup=False)

    state_str = "ENABLED 🔴" if new_state else "DISABLED 🟢"
    safe_reply(bot, message, f"🛠️ Maintenance mode is now <b>{state_str}</b>.")

    # Auto Broadcast to all registered users
    users_db = load_data(USER_FILE)
    if isinstance(users_db, dict) and users_db:
        broadcast_msg = (
            "🛠️ <b>System Notice:</b> Bot is currently entering scheduled maintenance. Features may be temporarily unavailable."
            if new_state
            else "🟢 <b>System Notice:</b> Scheduled maintenance has concluded! All 7G Master Bot features are fully active."
        )
        def broadcast_worker():
            for uid in list(users_db.keys()):
                try:
                    bot.send_message(int(uid), broadcast_msg, parse_mode="HTML")
                    time.sleep(0.05)
                except Exception:
                    pass
        EXECUTOR.submit(broadcast_worker)

@bot.message_handler(commands=["broadcast"])
def handle_broadcast(message: types.Message):
    user = message.from_user
    if user.id != ADMIN_ID:
        return
    broadcast_text = message.text.replace("/broadcast", "", 1).strip()
    if not broadcast_text:
        safe_reply(bot, message, "Usage: <code>/broadcast &lt;your message&gt;</code>")
        return

    users_db = load_data(USER_FILE)
    if not isinstance(users_db, dict) or not users_db:
        safe_reply(bot, message, "No registered users to broadcast to.")
        return

    status_msg = safe_reply(bot, message, f"📢 Starting broadcast to {len(users_db)} users...")

    def broadcast_job():
        success = 0
        failed = 0
        formatted_announcement = (
            f"📢 <b>Global Announcement:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{escape(broadcast_text)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        for uid in list(users_db.keys()):
            try:
                bot.send_message(int(uid), formatted_announcement, parse_mode="HTML")
                success += 1
                time.sleep(0.05)
            except Exception:
                failed += 1

        try:
            bot.edit_message_text(
                f"✅ <b>Broadcast Completed!</b>\nDelivered: <code>{success}</code>\nFailed: <code>{failed}</code>",
                message.chat.id,
                status_msg.message_id,
                parse_mode="HTML"
            )
        except Exception:
            pass

    EXECUTOR.submit(broadcast_job)

# ----------------- CLONE BOT SYSTEM ----------------- #

@bot.message_handler(commands=["clone"])
def handle_clone_command(message: types.Message):
    user = message.from_user
    if is_banned(user.id):
        return
    AWAITING_BOT_TOKEN.add(user.id)
    safe_reply(
        bot,
        message,
        "🤖 <b>Create Your Own Clone Bot!</b>\n\n"
        "1. Open @BotFather on Telegram.\n"
        "2. Create a new bot with <code>/newbot</code>.\n"
        "3. Copy the HTTP API Token and send it here now.\n\n"
        "<i>Send /cancel to abort.</i>"
    )

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call: types.CallbackQuery):
    try:
        if call.data == "clone_bot":
            AWAITING_BOT_TOKEN.add(call.from_user.id)
            bot.send_message(
                call.message.chat.id,
                "🤖 <b>Create Your Own Bot:</b>\nSend your Telegram Bot Token from @BotFather now:",
                parse_mode="HTML"
            )
            bot.answer_callback_query(call.id)
        elif call.data == "my_stats":
            users_db = load_data(USER_FILE)
            uid = str(call.from_user.id)
            info = users_db.get(uid, {})
            stats_msg = (
                f"👤 <b>Your Activity Profile:</b>\n"
                f"├ 💬 Messages Sent: <code>{info.get('msg_count', 0)}</code>\n"
                f"├ 📥 Downloads: <code>{info.get('downloads_count', 0)}</code>\n"
                f"├ 🎁 Referral Points: <code>{info.get('points', 0)}</code>\n"
                f"└ 👥 Friends Invited: <code>{len(info.get('referrals', []))}</code>"
            )
            bot.send_message(call.message.chat.id, stats_msg, parse_mode="HTML")
            bot.answer_callback_query(call.id)
    except Exception as e:
        log_error(f"Callback error: {e}")

def start_clone_bot(token: str, owner_id: int):
    """Spins up an independent TeleBot polling thread with Gemini AI and Pollinations."""
    try:
        clean_token = token.strip()
        clone = telebot.TeleBot(clean_token, parse_mode=None)
        me = clone.get_me()
        log(f"Starting Clone Bot @{me.username} for owner {owner_id}")

        @clone.message_handler(commands=["start"])
        def clone_start(msg):
            clone.reply_to(msg, f"👋 Hello {msg.from_user.first_name}! I am a 7G Clone Bot powered by Gemini 1.5 Flash.")

        @clone.message_handler(commands=["ai"])
        def clone_ai(msg):
            q = msg.text.replace("/ai", "", 1).strip()
            if q:
                res = call_gemini_ai(q, user_name=msg.from_user.first_name)
                chunk_and_send(clone, msg.chat.id, res)

        @clone.message_handler(commands=["image"])
        def clone_image(msg):
            p = msg.text.replace("/image", "", 1).strip()
            if p:
                img_url, img_bytes = generate_pollinations_image(p)
                if img_bytes:
                    f = io.BytesIO(img_bytes)
                    f.name = "image.jpg"
                    clone.send_photo(msg.chat.id, f)
                elif img_url:
                    clone.send_photo(msg.chat.id, img_url)

        ACTIVE_CLONES[clean_token] = clone
        clone.infinity_polling(skip_pending=True)
    except Exception as e:
        log_error(f"Clone bot execution failed: {e}")

# ----------------- UNIVERSAL MESSAGE & DOWNLOAD LISTENER ----------------- #

@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_all_text_messages(message: types.Message):
    user = message.from_user
    text = (message.text or "").strip()

    if is_banned(user.id):
        return

    # Check awaiting bot token state
    if user.id in AWAITING_BOT_TOKEN:
        AWAITING_BOT_TOKEN.remove(user.id)
        if text.lower() == "/cancel":
            safe_reply(bot, message, "❌ Operation cancelled.")
            return
        if ":" in text and len(text) > 30:
            status = safe_reply(bot, message, "⏳ Validating bot token and launching clone...")
            try:
                test_bot = telebot.TeleBot(text)
                bot_info = test_bot.get_me()
                EXECUTOR.submit(start_clone_bot, text, user.id)
                safe_reply(bot, message, f"🎉 <b>Success!</b> Your bot @{bot_info.username} is now online and active 24/7!")
            except Exception as e:
                safe_reply(bot, message, f"❌ Failed to start bot: Invalid token or Telegram API error ({escape(str(e))}).")
            return
        else:
            safe_reply(bot, message, "❌ Invalid bot token format. Please try /clone again.")
            return

    # Maintenance check
    if is_maintenance_active() and user.id != ADMIN_ID:
        safe_reply(bot, message, "🛠️ Bot is currently undergoing maintenance. Please check back shortly!")
        return

    # 1. Instagram Link Handler
    if "instagram.com" in text:
        track_user_activity(user, "Instagram Download", text)
        status_msg = safe_reply(bot, message, "⏳ <b>Processing Instagram HD download...</b>")

        def ig_job():
            candidate = download_instagram(text)
            if status_msg:
                try:
                    bot.delete_message(message.chat.id, status_msg.message_id)
                except Exception:
                    pass

            if candidate:
                try:
                    if os.path.exists(candidate):
                        with open(candidate, "rb") as vf:
                            bot.send_video(message.chat.id, vf, caption="📥 <b>Downloaded via 7G Master Bot</b> ✨", parse_mode="HTML")
                        try:
                            os.remove(candidate)
                        except Exception:
                            pass
                    else:
                        bot.send_video(message.chat.id, candidate, caption="📥 <b>Downloaded via 7G Master Bot</b> ✨", parse_mode="HTML")
                    return
                except Exception as send_err:
                    log_error(f"Sending Instagram media failed: {send_err}")
            safe_reply(bot, message, "⚠️ দুঃখিত, এই ইনস্টাগ্রাম রিল/পোস্টটি ডাউনলোড করা সম্ভব হয়নি। লিঙ্কটি প্রাইভেট বা আনসাপোর্টেড হতে পারে।")

        EXECUTOR.submit(ig_job)
        return

    # 2. TikTok Link Handler
    if "tiktok.com" in text:
        track_user_activity(user, "TikTok Download", text)
        status_msg = safe_reply(bot, message, "⏳ <b>Processing TikTok HD download (No Watermark)...</b>")

        def tt_job():
            candidate = download_tiktok(text)
            if status_msg:
                try:
                    bot.delete_message(message.chat.id, status_msg.message_id)
                except Exception:
                    pass

            if candidate:
                try:
                    if os.path.exists(candidate):
                        with open(candidate, "rb") as vf:
                            bot.send_video(message.chat.id, vf, caption="📥 <b>TikTok HD (No Watermark) via 7G Master Bot</b> ✨", parse_mode="HTML")
                        try:
                            os.remove(candidate)
                        except Exception:
                            pass
                    else:
                        bot.send_video(message.chat.id, candidate, caption="📥 <b>TikTok HD (No Watermark) via 7G Master Bot</b> ✨", parse_mode="HTML")
                    return
                except Exception as send_err:
                    log_error(f"Sending TikTok media failed: {send_err}")
            safe_reply(bot, message, "⚠️ দুঃখিত, এই টিকটক ভিডিওটি ডাউনলোড করা সম্ভব হয়নি। অনুগ্রহ করে লিঙ্কটি পুনরায় পরীক্ষা করুন।")

        EXECUTOR.submit(tt_job)
        return

    # 3. Default Natural Conversation with Google Gemini 1.5 Flash
    track_user_activity(user, "Natural Chat (Gemini)", text)
    process_gemini_query(bot, message, text)

# ----------------- MAIN BOOTSTRAPPER ----------------- #

def main():
    log("=========================================================")
    log("🚀 Starting 7G Ultimate Telegram Master Bot (Enterprise)")
    log("=========================================================")
    log(f"Admin ID: {ADMIN_ID}")
    log(f"Gemini AI Engine: {'CONFIGURED ✅' if (os.getenv('GEMINI_API_KEY') or GEMINI_API_KEY) else 'MISSING ⚠️ (Set GEMINI_API_KEY)'}")
    log(f"Pollinations Image Engine: READY ✅")

    # Start Flask 24/7 Keep-Alive Server Thread
    flask_thread = threading.Thread(target=run_flask, daemon=True, name="FlaskThread")
    flask_thread.start()

    # Start Render 24/7 Self-Ping Keep-Alive Thread
    ping_thread = threading.Thread(target=keep_alive_ping_loop, daemon=True, name="SelfPingThread")
    ping_thread.start()

    # Start TeleBot Polling with Automatic Reconnect Loop
    log("Starting Telegram Bot long-polling...")
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=30)
        except Exception as poll_err:
            log_error(f"Telegram polling exception: {poll_err}. Reconnecting in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    main()
