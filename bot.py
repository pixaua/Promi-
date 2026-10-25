"""
=============================================================================
7G ULTIMATE TELEGRAM MASTER BOT (ENTERPRISE PRODUCTION EDITION)
=============================================================================
Primary Token: 7678905793:AAHvRXVmRSF1UlC_T5Gn3K0j4n2PeZB8fmA
Master Admin ID: 6162953772
RapidAPI Key: 8ab82c2a2fmshd7c1d7c96acc63fp170cfajsnd4d72661f86a
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
import tempfile
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
from telebot import types
import yt_dlp

# Ensure static ffmpeg paths if installed (for Render / cloud environments)
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

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
MAIN_BOT_TOKEN = os.getenv("BOT_TOKEN", "7678905793:AAHvRXVmRSF1UlC_T5Gn3K0j4n2PeZB8fmA").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "6162953772"))

# RapidAPI Integrations (Instagram Guaranteed Audio Autolink & Media Downloader)
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "8ab82c2a2fmshd7c1d7c96acc63fp170cfajsnd4d72661f86a").strip()
RAPIDAPI_IG_HOST = "social-download-all-in-one.p.rapidapi.com"
RAPIDAPI_YT_HOST = "youtube-media-downloader.p.rapidapi.com"

META_AI_KEY = os.getenv("META_AI_API_KEY", "nxt_3a454c41e6a84aeead28d1fb4aec87a4").strip()
META_AI_GEM_ID = os.getenv("META_AI_GEM_ID", "ba0fbe0d-976e-493a-afdb-6d8469e53df0")
META_AI_ENDPOINT = f"https://nxtai.zipohostbd.workers.dev/api/use?gem={META_AI_GEM_ID}"
IMAGE_FALLBACK_ENDPOINT = "https://image.pollinations.ai/prompt/"
TIKWM_ENDPOINT = "https://www.tikwm.com/api/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

MAX_TEXT_LENGTH = 3900
TELEGRAM_CHUNK_LIMIT = 3900

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
USER_FILE = os.path.join(DATA_DIR, "users_db.json")
BANNED_FILE = os.path.join(DATA_DIR, "banned_users.json")
CONFIG_FILE = os.path.join(DATA_DIR, "bot_config.json")
CLONES_FILE = os.path.join(DATA_DIR, "clones_db.json")

# State & Concurrency (Optimized for High Speed)
FILE_LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=15, thread_name_prefix="7g_fast_worker")
ACTIVE_CLONES: dict[str, telebot.TeleBot] = {}
STOPPED_CLONES: set[str] = set()
AWAITING_BOT_TOKEN: set[int] = set()

# Pending Downloads Cache
DOWNLOAD_CACHE: dict[str, dict[str, Any]] = {}
CACHE_LOCK = threading.Lock()

# Global Pooled HTTP Session
HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"User-Agent": USER_AGENT})

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
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip() or os.getenv("KEEP_ALIVE_URL", "").strip()
    if not render_url:
        log("Keep-alive self-ping: Waiting for RENDER_EXTERNAL_URL or live traffic.")
        return

    target_url = render_url.rstrip("/") + "/healthz"
    log(f"Keep-alive self-ping loop active for {target_url} (interval: ~11-13 mins)")
    while True:
        time.sleep(random.uniform(11 * 60, 13 * 60))
        try:
            res = HTTP_SESSION.get(target_url, timeout=15)
            log(f"Keep-alive ping success: HTTP {res.status_code}")
        except Exception as ping_err:
            log_error(f"Keep-alive ping warning: {ping_err}")

# ----------------- DOWNLOAD CACHE HELPER ----------------- #
def register_download_task(url: str, platform: str, user_id: int) -> str:
    with CACHE_LOCK:
        now = time.time()
        expired = [k for k, v in DOWNLOAD_CACHE.items() if now - v.get("timestamp", 0) > 21600]
        for k in expired:
            DOWNLOAD_CACHE.pop(k, None)

        short_id = uuid.uuid4().hex[:10]
        DOWNLOAD_CACHE[short_id] = {
            "url": url,
            "platform": platform,
            "user_id": user_id,
            "timestamp": now
        }
        return short_id

def get_download_task(short_id: str) -> dict[str, Any] | None:
    with CACHE_LOCK:
        return DOWNLOAD_CACHE.get(short_id)

# ----------------- DATABASE MANAGEMENT WITH AUTO TELEGRAM BACKUP ----------------- #
def load_data(filepath: str) -> Any:
    with FILE_LOCK:
        if not os.path.exists(filepath):
            return {} if ("users" in filepath or "config" in filepath or "clones" in filepath) else []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_error(f"Error reading {filepath}: {e}")
            return {} if ("users" in filepath or "config" in filepath or "clones" in filepath) else []

def save_data(filepath: str, data: Any, trigger_backup: bool = False) -> None:
    with FILE_LOCK:
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            log_error(f"Error saving {filepath}: {e}")
            return

    if trigger_backup and "users_db.json" in filepath:
        EXECUTOR.submit(trigger_telegram_db_backup, filepath)

def trigger_telegram_db_backup(filepath: str) -> None:
    try:
        if os.path.exists(filepath):
            with open(filepath, "rb") as bf:
                bot.send_document(
                    ADMIN_ID,
                    bf,
                    caption=(
                        f"🛡️ <b>Auto Telegram Database Backup Sync</b> ✨\n"
                        f"🕒 <i>Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>\n"
                        f"💡 <i>Tip: Send this file to the bot with caption /restoredb anytime to restore data on Render!</i>"
                    ),
                    parse_mode="HTML"
                )
    except Exception as e:
        log_error(f"Auto DB Backup to Telegram failed: {e}")

def get_config() -> dict[str, Any]:
    config = load_data(CONFIG_FILE)
    if not isinstance(config, dict):
        config = {"maintenance": False}
        save_data(CONFIG_FILE, config)
    return config

def is_banned(user_id: int | str) -> bool:
    banned_list = load_data(BANNED_FILE)
    if not isinstance(banned_list, list):
        return False
    return str(user_id) in [str(u) for u in banned_list]

def escape(text: Any) -> str:
    return html.escape(str(text)) if text else ""

def safe_reply(
    bot_instance: telebot.TeleBot,
    message: telebot.types.Message,
    text: str,
    parse_mode: str | None = None,
    reply_markup: Any = None
) -> telebot.types.Message | None:
    try:
        return bot_instance.reply_to(message, text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as err:
        log_error(f"Reply error ({err}); sending as plain message.")
        try:
            return bot_instance.send_message(message.chat.id, text, reply_markup=reply_markup)
        except Exception as final_err:
            log_error(f"Failed to deliver safe message: {final_err}")
            return None

def chunk_and_send(
    bot_instance: telebot.TeleBot,
    chat_id: int,
    text: str,
    parse_mode: str | None = None
) -> None:
    if len(text) <= TELEGRAM_CHUNK_LIMIT:
        try:
            bot_instance.send_message(chat_id, text, parse_mode=parse_mode)
            return
        except Exception:
            bot_instance.send_message(chat_id, text, parse_mode=None)
            return

    lines = text.split("\n")
    current_chunk = ""
    for line in lines:
        if len(current_chunk) + len(line) + 1 > TELEGRAM_CHUNK_LIMIT:
            try:
                bot_instance.send_message(chat_id, current_chunk, parse_mode=parse_mode)
            except Exception:
                bot_instance.send_message(chat_id, current_chunk, parse_mode=None)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"

    if current_chunk.strip():
        try:
            bot_instance.send_message(chat_id, current_chunk, parse_mode=parse_mode)
        except Exception:
            bot_instance.send_message(chat_id, current_chunk, parse_mode=None)

# ----------------- USER TRACKING & STATS RECORDING ----------------- #
def track_user_activity(
    user: telebot.types.User,
    action_type: str,
    text_data: str = "",
    referred_by: int | None = None
) -> None:
    try:
        user_id = str(user.id)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Map language code to human-readable nationality / country info
        lang_code = (user.language_code or "en").lower()
        country_map = {
            "bn": "🇧🇩 Bangladesh (Bengali)",
            "en": "🌐 International (English)",
            "hi": "🇮🇳 India (Hindi)",
            "ur": "🇵🇰 Pakistan (Urdu)",
            "ar": "🇸🇦 Middle East (Arabic)",
            "es": "🇪🇸 Spain / LatAm (Spanish)",
            "fr": "🇫🇷 France (French)",
            "de": "🇩🇪 Germany (German)",
            "ru": "🇷🇺 Russia (Russian)",
            "id": "🇮🇩 Indonesia (Indonesian)",
            "tr": "🇹🇷 Turkey (Turkish)",
        }
        nationality_label = country_map.get(lang_code, f"🌐 {lang_code.upper()} Region")

        with FILE_LOCK:
            users_db = load_data(USER_FILE)
            if not isinstance(users_db, dict):
                users_db = {}

            if user_id not in users_db:
                users_db[user_id] = {
                    "first_name": user.first_name or "Unknown",
                    "username": f"@{user.username}" if user.username else "No Username",
                    "language_code": user.language_code or "N/A",
                    "nationality": nationality_label,
                    "first_seen": now_str,
                    "last_seen": now_str,
                    "msg_count": 1,
                    "downloads_count": 1 if "Download" in action_type else 0,
                    "messages": [text_data] if text_data and "Download" not in action_type else [],
                    "download_links": [text_data] if "Download" in action_type and text_data else [],
                    "referred_by": str(referred_by) if referred_by else None,
                    "referrals": [],
                    "points": 0
                }

                if referred_by and str(referred_by) in users_db and str(referred_by) != user_id:
                    ref_profile = users_db[str(referred_by)]
                    if "referrals" not in ref_profile or not isinstance(ref_profile["referrals"], list):
                        ref_profile["referrals"] = []
                    if user_id not in ref_profile["referrals"]:
                        ref_profile["referrals"].append(user_id)
                        ref_profile["points"] = ref_profile.get("points", 0) + 10
                        try:
                            bot.send_message(
                                referred_by,
                                f"🎉 <b>New Referral Joined!</b>\n"
                                f"User: <b>{escape(user.first_name)}</b> joined via your link!\n"
                                f"✨ You earned +10 reward points! 🌟",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass
            else:
                profile = users_db[user_id]
                profile["first_name"] = user.first_name or profile.get("first_name", "Unknown")
                if user.username:
                    profile["username"] = f"@{user.username}"
                profile["language_code"] = user.language_code or profile.get("language_code", "N/A")
                profile["nationality"] = nationality_label
                profile["last_seen"] = now_str
                profile["msg_count"] = profile.get("msg_count", 0) + 1

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

def send_admin_alert(
    user: telebot.types.User,
    action_type: str,
    text_data: str,
    user_info: dict[str, Any]
) -> None:
    try:
        preview_data = text_data[:240] + ("..." if len(text_data) > 240 else "")
        alert_msg = (
            f"🚨 <b>New Activity Alert!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>User:</b> {escape(user_info.get('first_name', 'Unknown'))} ({escape(user_info.get('username', 'No Username'))})\n"
            f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
            f"🌐 <b>Country:</b> {escape(user_info.get('nationality', 'N/A'))}\n"
            f"⚡ <b>Action:</b> {escape(action_type)}\n"
            f"📌 <b>Data:</b> <code>{escape(preview_data)}</code>\n"
            f"🕒 <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>"
        )
        bot.send_message(ADMIN_ID, alert_msg, parse_mode="HTML")
    except Exception as e:
        log_error("Failed to send admin activity alert: %s", e)

# ----------------- ADVANCED DOWNLOAD & EXTRACTION UTILITIES ----------------- #

def download_to_temp_file(
    media_url: str,
    suffix: str = ".mp4",
    referer: str = "https://www.google.com/"
) -> str | None:
    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": referer,
            "Accept": "*/*",
        }
        with HTTP_SESSION.get(media_url, headers=headers, stream=True, timeout=90) as resp:
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                total_bytes = 0
                for chunk in resp.iter_content(chunk_size=512 * 1024):
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

# ----------------- INSTAGRAM DOWNLOADER (GUARANTEED AUDIO) ----------------- #

def download_instagram(url: str, extract_audio: bool = False) -> tuple[str, str | None]:
    clean_url = url.strip()
    m = re.search(r"https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/[A-Za-z0-9_-]+", clean_url)
    if m:
        clean_url = m.group(0).rstrip("/") + "/"
    else:
        clean_url = clean_url.split("?")[0].rstrip("/") + "/"

    shortcode_match = re.search(r"/(?:reel|p|tv)/([A-Za-z0-9_-]+)", clean_url)
    shortcode = shortcode_match.group(1) if shortcode_match else None

    temp_dir = tempfile.gettempdir()
    prefix = f"ig_{uuid.uuid4().hex[:8]}"

    # Method 0: RapidAPI Social Download All-in-One (autolink - 100% Guaranteed Audio)
    if RAPIDAPI_KEY:
        try:
            rapid_headers = {
                "x-rapidapi-key": RAPIDAPI_KEY,
                "x-rapidapi-host": RAPIDAPI_IG_HOST,
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "Accept": "application/json"
            }
            resp = HTTP_SESSION.post(
                f"https://{RAPIDAPI_IG_HOST}/v1/social/autolink",
                json={"url": clean_url},
                headers=rapid_headers,
                timeout=12
            )
            if resp.status_code == 200:
                data = resp.json()
                medias = data.get("medias", []) or data.get("media", []) or data.get("data", [])
                title = data.get("title") or "Instagram Media"
                if isinstance(medias, list) and medias:
                    best_m = None
                    if extract_audio:
                        for item in medias:
                            if isinstance(item, dict) and item.get("type") == "audio" and item.get("url"):
                                best_m = item.get("url")
                                break
                    if not best_m:
                        for item in medias:
                            if isinstance(item, dict) and item.get("url"):
                                best_m = item.get("url")
                                break
                            elif isinstance(item, str) and item.startswith("http"):
                                best_m = item
                                break

                    if best_m:
                        suffix = ".m4a" if extract_audio else ".mp4"
                        tmp_file = download_to_temp_file(best_m, suffix=suffix, referer="https://www.instagram.com/")
                        if tmp_file and os.path.exists(tmp_file) and os.path.getsize(tmp_file) > 1000:
                            return title, tmp_file
        except Exception as rapid_ig_err:
            log_error(f"RapidAPI Instagram autolink error: {rapid_ig_err}")

    # Method 1: yt-dlp Native Direct Downloader with audio guaranteed selector
    try:
        out_tmpl = os.path.join(temp_dir, f"{prefix}.%(ext)s")
        if extract_audio:
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': out_tmpl,
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'nocheckcertificate': True,
                'source_address': '0.0.0.0',
                'cachedir': False,
            }
        else:
            ydl_opts = {
                'format': 'best[vcodec!=none][acodec!=none]/bestvideo+bestaudio/best',
                'outtmpl': out_tmpl,
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'nocheckcertificate': True,
                'source_address': '0.0.0.0',
                'cachedir': False,
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=True)
            if info:
                title = info.get("title") or "Instagram Media"
                candidate_path = ydl.prepare_filename(info)
                if os.path.exists(candidate_path) and os.path.getsize(candidate_path) > 1000:
                    return title, candidate_path
                for f in os.listdir(temp_dir):
                    if f.startswith(prefix):
                        f_path = os.path.join(temp_dir, f)
                        if os.path.getsize(f_path) > 1000:
                            return title, f_path
    except Exception as ydl_err:
        log_error(f"yt-dlp Instagram download failed: {ydl_err}")

    # Method 2: Instaloader Native Extractor
    if shortcode:
        try:
            import instaloader
            L = instaloader.Instaloader(quiet=True, download_comments=False)
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            caption = post.caption or "Instagram Media"
            if getattr(post, "is_video", False) and getattr(post, "video_url", None):
                suffix = ".m4a" if extract_audio else ".mp4"
                tmp_file = download_to_temp_file(post.video_url, suffix=suffix, referer="https://www.instagram.com/")
                if tmp_file:
                    return caption, tmp_file
                return caption, post.video_url
            elif getattr(post, "url", None) and not extract_audio:
                tmp_file = download_to_temp_file(post.url, suffix=".jpg", referer="https://www.instagram.com/")
                if tmp_file:
                    return caption, tmp_file
                return caption, post.url
        except Exception as inst_err:
            log_error(f"Instaloader Instagram fallback failed: {inst_err}")

    # Method 3: SaveInsta / Snapinsta Web Resolver
    try:
        headers = {
            'User-Agent': USER_AGENT,
            'Referer': 'https://saveinsta.app/',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
        }
        endpoints = [
            "https://v3.saveinsta.app/api/ajaxSearch",
            "https://saveinsta.io/api/ajaxSearch",
            "https://snapinsta.to/api/ajaxSearch"
        ]
        for ep in endpoints:
            try:
                res = HTTP_SESSION.post(ep, data={"q": clean_url, "t": "media", "lang": "en"}, headers=headers, timeout=12)
                if res.status_code == 200:
                    resp_json = res.json()
                    html_content = resp_json.get("data", "")
                    m_url = re.search(r'href="([^"]+)"[^>]*class="[^"]*btn-download[^"]*"', html_content) or re.search(r'href="([^"]+)"[^>]*download', html_content)
                    if m_url:
                        video_link = html.unescape(m_url.group(1))
                        suffix = ".m4a" if extract_audio else ".mp4"
                        tmp_file = download_to_temp_file(video_link, suffix=suffix, referer="https://saveinsta.app/")
                        if tmp_file:
                            return "Instagram Video", tmp_file
                        return "Instagram Video", video_link
            except Exception:
                pass
    except Exception as save_err:
        log_error(f"SaveInsta resolver failed: {save_err}")

    return "Instagram Media", None

# ----------------- TIKTOK DOWNLOADER (HD NO WATERMARK + AUDIO) ----------------- #

def download_tiktok(url: str, extract_audio: bool = False) -> tuple[str, str | None]:
    clean_url = url.strip()
    m = re.search(r'https?://(?:www\.|vt\.|vm\.|m\.)?tiktok\.com/[^\s\?]+', clean_url)
    base_clean_url = m.group(0) if m else clean_url.split("?")[0]

    if "vt.tiktok.com" in clean_url or "vm.tiktok.com" in clean_url:
        try:
            head_resp = HTTP_SESSION.head(clean_url, allow_redirects=True, timeout=10)
            if head_resp.url and "tiktok.com" in head_resp.url:
                clean_url = head_resp.url
                m2 = re.search(r'https?://(?:www\.|vt\.|vm\.|m\.)?tiktok\.com/[^\s\?]+', clean_url)
                base_clean_url = m2.group(0) if m2 else clean_url.split("?")[0]
        except Exception:
            pass

    # 1. TikWM API (HD / Normal / MP3)
    tikwm_endpoints = ["https://www.tikwm.com/api/", "https://tikwm.com/api/"]
    for endpoint in tikwm_endpoints:
        for target_u in [clean_url, base_clean_url]:
            try:
                res = HTTP_SESSION.post(
                    endpoint,
                    data={"url": target_u, "hd": 1},
                    headers={"Accept": "application/json"},
                    timeout=15
                ).json()
                if isinstance(res, dict) and res.get("code") == 0 and "data" in res:
                    data = res["data"]
                    title = str(data.get("title") or "TikTok Video")

                    if extract_audio:
                        music_url = data.get("music") or data.get("play")
                        if music_url:
                            if music_url.startswith("/"):
                                music_url = f"https://www.tikwm.com{music_url}"
                            tmp_file = download_to_temp_file(music_url, suffix=".mp3", referer="https://www.tikwm.com/")
                            if tmp_file:
                                return title, tmp_file
                            return title, music_url
                    else:
                        video_url = data.get("hdplay") or data.get("play") or data.get("wmplay")
                        if video_url:
                            if video_url.startswith("/"):
                                video_url = f"https://www.tikwm.com{video_url}"
                            tmp_file = download_to_temp_file(video_url, suffix=".mp4", referer="https://www.tikwm.com/")
                            if tmp_file:
                                return title, tmp_file
                            return title, video_url
            except Exception as e:
                log_error(f"TikWM attempt error on {endpoint}: {e}")

    # 2. yt-dlp Native Direct Downloader
    try:
        temp_dir = tempfile.gettempdir()
        prefix = f"tt_{uuid.uuid4().hex[:8]}"
        out_tmpl = os.path.join(temp_dir, f"{prefix}.%(ext)s")
        if extract_audio:
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': out_tmpl,
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'nocheckcertificate': True,
                'source_address': '0.0.0.0',
            }
        else:
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': out_tmpl,
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'nocheckcertificate': True,
                'source_address': '0.0.0.0',
            }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=True)
            if info:
                title = info.get("title") or "TikTok Video"
                candidate_path = ydl.prepare_filename(info)
                if os.path.exists(candidate_path) and os.path.getsize(candidate_path) > 1000:
                    return title, candidate_path
                for f in os.listdir(temp_dir):
                    if f.startswith(prefix):
                        f_path = os.path.join(temp_dir, f)
                        if os.path.getsize(f_path) > 1000:
                            return title, f_path
    except Exception as ydl_tt_err:
        log_error(f"yt-dlp TikTok fallback failed: {ydl_tt_err}")

    return "TikTok Media", None

# ----------------- YOUTUBE DOWNLOADER (VIDEOS & SHORTS + MP3) ----------------- #

def extract_youtube_id(url: str) -> str | None:
    patterns = [
        r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/|\/live\/)([a-zA-Z0-9_-]{11})",
        r"^[a-zA-Z0-9_-]{11}$"
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None

def download_youtube_loader_stream(canonical_url: str, extract_audio: bool = False) -> tuple[str, str | None]:
    """
    High-Speed Cloud Resolver:
    Converts and downloads YouTube media via independent CDN pipelines.
    Completely bypasses YouTube datacenter IP-locks and Google 403 Forbidden!
    """
    fmt = "mp3" if extract_audio else "720"
    init_url = f"https://loader.to/ajax/download.php?format={fmt}&url={quote(canonical_url)}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    try:
        req = Request(init_url, headers=headers)
        with urlopen(req, timeout=12) as res:
            data = json.loads(res.read().decode("utf-8"))
            job_id = data.get("id")
            title = data.get("title") or "YouTube Media"
            if not job_id:
                return title, None

        for _ in range(12):
            time.sleep(1.8)
            prog_url = f"https://loader.to/ajax/progress.php?id={job_id}"
            preq = Request(prog_url, headers=headers)
            with urlopen(preq, timeout=10) as pres:
                pdata = json.loads(pres.read().decode("utf-8"))
                download_url = pdata.get("download_url")
                if download_url:
                    suffix = ".mp3" if extract_audio else ".mp4"
                    tmp_f = download_to_temp_file(download_url, suffix=suffix, referer="https://loader.to/")
                    if tmp_f and os.path.exists(tmp_f) and os.path.getsize(tmp_f) > 1000:
                        return title, tmp_f
                if pdata.get("success") == 1 and download_url:
                    suffix = ".mp3" if extract_audio else ".mp4"
                    tmp_f = download_to_temp_file(download_url, suffix=suffix, referer="https://loader.to/")
                    if tmp_f and os.path.exists(tmp_f) and os.path.getsize(tmp_f) > 1000:
                        return title, tmp_f
    except Exception as loader_err:
        log_error(f"Loader.to resolver error: {loader_err}")

    return "YouTube Media", None

def download_youtube(url: str, extract_audio: bool = False) -> tuple[str, str | None]:
    """
    Multi-Tier YouTube Downloader:
    Tier 1: Cloud CDN Web Resolver (100% bypasses Google datacenter IP-lock)
    Tier 2: Native yt-dlp with mobile client spoofing ('mweb', 'android', 'tv_embedded') + IPv4 socket
    Tier 3: Multi-Instance Public Invidious stream resolver
    """
    clean_url = url.strip()
    vid_id = extract_youtube_id(clean_url)
    target_url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else clean_url

    temp_dir = tempfile.gettempdir()
    prefix = f"yt_{uuid.uuid4().hex[:8]}"
    default_title = "YouTube Media"

    # Tier 1: Cloud CDN Web Resolver (Most reliable on Render & VPS datacenters)
    t1_title, t1_file = download_youtube_loader_stream(target_url, extract_audio=extract_audio)
    if t1_file and os.path.exists(t1_file) and os.path.getsize(t1_file) > 1000:
        return t1_title, t1_file

    # Tier 2: yt-dlp Native Download with Mobile Client Spoofing
    cookie_file = None
    if os.path.exists("cookies.txt"):
        cookie_file = os.path.abspath("cookies.txt")
    elif os.getenv("YT_COOKIES"):
        try:
            cf = os.path.join(temp_dir, f"yt_cookies_{uuid.uuid4().hex[:6]}.txt")
            with open(cf, "w", encoding="utf-8") as f:
                f.write(os.getenv("YT_COOKIES", ""))
            cookie_file = cf
        except Exception:
            pass

    player_client_sets = [
        ['mweb'],
        ['android'],
        ['ios'],
        ['tv_embedded'],
        ['web']
    ]

    if extract_audio:
        format_spec = "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/140/ba/b"
    else:
        format_spec = (
            "best[ext=mp4][height<=720][vcodec!=none][acodec!=none]/"
            "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/"
            "22/18/"
            "best[height<=720]/best"
        )

    for client_list in player_client_sets:
        client_name = client_list[0] if client_list else "default"
        out_tmpl = os.path.join(temp_dir, f"{prefix}_{client_name}.%(ext)s")

        ydl_opts: dict[str, Any] = {
            'format': format_spec,
            'outtmpl': out_tmpl,
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'nocheckcertificate': True,
            'source_address': '0.0.0.0',
            'cachedir': False,
            'ignoreerrors': True,
        }
        if cookie_file and os.path.exists(cookie_file):
            ydl_opts['cookiefile'] = cookie_file
        if client_list:
            ydl_opts['extractor_args'] = {'youtube': {'player_client': client_list}}

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                if info:
                    title = info.get("title") or default_title
                    candidate_path = ydl.prepare_filename(info)
                    if os.path.exists(candidate_path) and os.path.getsize(candidate_path) > 1000:
                        return title, candidate_path
                    for f in os.listdir(temp_dir):
                        if f.startswith(f"{prefix}_{client_name}"):
                            f_path = os.path.join(temp_dir, f)
                            if os.path.getsize(f_path) > 1000:
                                return title, f_path
        except Exception as dl_err:
            log_error(f"yt-dlp YouTube {client_list} failed: {dl_err}")
            continue

    # Tier 3: Invidious Resolver
    if vid_id:
        invidious_instances = [
            "https://inv.tux.pizza",
            "https://invidious.nerdvpn.de",
            "https://invidious.jing.rocks",
            "https://yt.artemislena.eu"
        ]
        for inv_host in invidious_instances:
            try:
                api_url = f"{inv_host}/api/v1/videos/{vid_id}"
                resp = HTTP_SESSION.get(api_url, timeout=10, headers={"User-Agent": USER_AGENT})
                if resp.status_code == 200:
                    data = resp.json()
                    title = data.get("title") or default_title
                    if extract_audio:
                        for af in data.get("adaptiveFormats", []):
                            if af.get("type", "").startswith("audio"):
                                stream_url = af.get("url")
                                if stream_url:
                                    ext = ".m4a" if "mp4a" in af.get("type", "") else ".mp3"
                                    tmp_f = download_to_temp_file(stream_url, suffix=ext, referer=inv_host)
                                    if tmp_f and os.path.exists(tmp_f) and os.path.getsize(tmp_f) > 1000:
                                        return title, tmp_f
                    else:
                        for fs in reversed(data.get("formatStreams", [])):
                            stream_url = fs.get("url")
                            if stream_url:
                                tmp_f = download_to_temp_file(stream_url, suffix=".mp4", referer=inv_host)
                                if tmp_f and os.path.exists(tmp_f) and os.path.getsize(tmp_f) > 1000:
                                    return title, tmp_f
            except Exception:
                continue

    return default_title, None

# ----------------- FACEBOOK DOWNLOADER (VIDEOS & REELS) ----------------- #

def download_facebook(url: str, extract_audio: bool = False) -> tuple[str, str | None]:
    clean_url = url.strip()
    temp_dir = tempfile.gettempdir()
    prefix = f"fb_{uuid.uuid4().hex[:8]}"
    out_tmpl = os.path.join(temp_dir, f"{prefix}.%(ext)s")

    try:
        if extract_audio:
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': out_tmpl,
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 35,
                'nocheckcertificate': True,
                'source_address': '0.0.0.0',
                'http_headers': {
                    'User-Agent': USER_AGENT,
                    'Referer': 'https://www.facebook.com/'
                },
            }
        else:
            ydl_opts = {
                'format': 'best[ext=mp4][vcodec!=none][acodec!=none]/best[ext=mp4]/best',
                'outtmpl': out_tmpl,
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 35,
                'nocheckcertificate': True,
                'source_address': '0.0.0.0',
                'http_headers': {
                    'User-Agent': USER_AGENT,
                    'Referer': 'https://www.facebook.com/'
                },
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=True)
            if info:
                title = info.get("title") or "Facebook Video"
                candidate_path = ydl.prepare_filename(info)
                if os.path.exists(candidate_path) and os.path.getsize(candidate_path) > 1000:
                    return title, candidate_path
                for f in os.listdir(temp_dir):
                    if f.startswith(prefix):
                        f_path = os.path.join(temp_dir, f)
                        if os.path.getsize(f_path) > 1000:
                            return title, f_path
    except Exception as fb_err:
        log_error(f"Facebook download failed: {fb_err}")

    return "Facebook Video", None

# ----------------- META AI & IMAGE GENERATION ENGINE ----------------- #

def query_meta_ai(prompt: str) -> str:
    payload = {
        "key": META_AI_KEY,
        "input": prompt.strip()
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }

    try:
        req = Request(
            META_AI_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urlopen(req, timeout=25) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                candidates = [
                    data.get("response"),
                    data.get("output"),
                    data.get("text"),
                    data.get("reply"),
                    data.get("message")
                ]
                for c in candidates:
                    if c and isinstance(c, str) and c.strip():
                        return c.strip()
    except Exception as e:
        log_error(f"Primary Meta AI endpoint error: {e}")

    try:
        fb_url = f"https://text.pollinations.ai/{quote(prompt)}?model=openai"
        res = HTTP_SESSION.get(fb_url, timeout=20)
        if res.status_code == 200 and res.text.strip():
            return res.text.strip()
    except Exception as fb_err:
        log_error(f"AI fallback endpoint error: {fb_err}")

    return "⚠️ <i>AI assistant is currently busy. Please ask again in a moment!</i>"

def send_ai_response(bot_instance: telebot.TeleBot, chat_id: int, prompt: str, status_msg_id: int | None = None) -> None:
    if prompt.lower().startswith("/image"):
        image_prompt = prompt[len("/image"):].strip()
        if not image_prompt:
            image_prompt = "Futuristic cyberpunk skyline 4k cinematic lighting"

        image_url = f"{IMAGE_FALLBACK_ENDPOINT}{quote(image_prompt)}?width=1024&height=1024&nologo=true"
        try:
            bot_instance.send_photo(
                chat_id,
                image_url,
                caption=f"🎨 <b>AI Generated Image</b>\nPrompt: <i>{escape(image_prompt)}</i>",
                parse_mode="HTML"
            )
            if status_msg_id:
                try:
                    bot_instance.delete_message(chat_id, status_msg_id)
                except Exception:
                    pass
            return
        except Exception as img_err:
            log_error(f"Direct photo send failed: {img_err}")
            tmp_img = download_to_temp_file(image_url, suffix=".jpg")
            if tmp_img and os.path.exists(tmp_img):
                try:
                    with open(tmp_img, "rb") as pf:
                        bot_instance.send_photo(
                            chat_id,
                            pf,
                            caption=f"🎨 <b>AI Generated Image</b>\nPrompt: <i>{escape(image_prompt)}</i>",
                            parse_mode="HTML"
                        )
                    if status_msg_id:
                        try:
                            bot_instance.delete_message(chat_id, status_msg_id)
                        except Exception:
                            pass
                    return
                finally:
                    try:
                        os.remove(tmp_img)
                    except Exception:
                        pass

        if status_msg_id:
            bot_instance.edit_message_text(
                "❌ <i>Failed to generate image. Please try a different prompt!</i>",
                chat_id,
                status_msg_id,
                parse_mode="HTML"
            )
        return

    # Text Chat
    reply = query_meta_ai(prompt)
    if status_msg_id:
        try:
            bot_instance.delete_message(chat_id, status_msg_id)
        except Exception:
            pass

    chunk_and_send(bot_instance, chat_id, reply, parse_mode="HTML")

# ----------------- UNIFIED DISPATCHER & INLINE HANDLERS ----------------- #

def prompt_media_choice(
    bot_instance: telebot.TeleBot,
    message: telebot.types.Message,
    url: str,
    platform: str
) -> None:
    short_id = register_download_task(url, platform, message.chat.id)

    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_video = types.InlineKeyboardButton("🎬 Video (HD)", callback_data=f"dl:v:{short_id}")
    btn_audio = types.InlineKeyboardButton("🎵 Audio (MP3)", callback_data=f"dl:a:{short_id}")
    markup.add(btn_video, btn_audio)

    # Ultra-Professional Platform UI Badges
    platform_info = {
        "instagram": ("📸 Instagram Reel / Post", "High-Definition Video with Full Audio Guarantee"),
        "tiktok": ("🎵 TikTok HD Media", "100% Watermark-Free HD Video & Studio Audio"),
        "youtube": ("🔴 YouTube Video / Shorts", "HD Quality 1080p/720p Video & MP3 Audio"),
        "facebook": ("🔵 Facebook Video / Reel", "High-Definition Video & High-Bitrate MP3")
    }
    title_label, desc_label = platform_info.get(platform, ("🎬 Media Stream", "Instant HD Media"))

    clean_preview = url[:70] + "..." if len(url) > 70 else url

    prompt_text = (
        f"⚡ <b>{title_label} Detected!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Source:</b> <code>{escape(clean_preview)}</code>\n"
        f"✨ <i>{desc_label}</i>\n\n"
        f"👇 <b>Select your desired format:</b>"
    )

    safe_reply(bot_instance, message, prompt_text, parse_mode="HTML", reply_markup=markup)

def process_download_execution(
    bot_instance: telebot.TeleBot,
    chat_id: int,
    status_msg_id: int,
    short_id: str,
    format_type: str
) -> None:
    task = get_download_task(short_id)
    if not task:
        bot_instance.edit_message_text(
            "⚠️ <b>This download link has expired.</b> Please send the link again!",
            chat_id,
            status_msg_id,
            parse_mode="HTML"
        )
        return

    url = task["url"]
    platform = task["platform"]
    extract_audio = (format_type == "a")
    format_label = "Audio (MP3)" if extract_audio else "Video (HD)"

    # Step 1: Animated Progress Bar - 30%
    try:
        bot_instance.edit_message_text(
            f"⏳ <b>Downloading {format_label}...</b>\n"
            f"[ ▰▰▰▱▱▱▱▱▱▱ ] <b>30%</b> • <i>Connecting to stream...</i>",
            chat_id,
            status_msg_id,
            parse_mode="HTML"
        )
    except Exception:
        pass

    local_file = None
    try:
        title = "Media Download"
        file_path = None

        if platform == "instagram":
            title, file_path = download_instagram(url, extract_audio=extract_audio)
        elif platform == "tiktok":
            title, file_path = download_tiktok(url, extract_audio=extract_audio)
        elif platform == "youtube":
            title, file_path = download_youtube(url, extract_audio=extract_audio)
        elif platform == "facebook":
            title, file_path = download_facebook(url, extract_audio=extract_audio)

        if not file_path:
            bot_instance.edit_message_text(
                f"❌ <b>Download Failed:</b> The {platform.capitalize()} media could not be fetched (it may be private, geo-blocked, or exceeds Telegram's 50MB limit).",
                chat_id,
                status_msg_id,
                parse_mode="HTML"
            )
            return

        # Step 2: Animated Progress Bar - 75%
        try:
            bot_instance.edit_message_text(
                f"⚡ <b>Processing {format_label}...</b>\n"
                f"[ ▰▰▰▰▰▰▰▱▱▱ ] <b>75%</b> • <i>Finalizing media packaging...</i>",
                chat_id,
                status_msg_id,
                parse_mode="HTML"
            )
        except Exception:
            pass

        caption_text = (
            f"📥 <b>{escape(title[:200])}</b>\n\n"
            f"⚡ <i>Downloaded via 7G Master Bot</i> ✨"
        )

        if os.path.isfile(file_path):
            local_file = file_path
            file_size_mb = os.path.getsize(local_file) / (1024 * 1024)
            if file_size_mb > 49.9:
                bot_instance.edit_message_text(
                    f"⚠️ <b>File Exceeds Limit:</b>\n"
                    f"This file is {file_size_mb:.1f} MB. Telegram Bot API only supports files up to 50MB.",
                    chat_id,
                    status_msg_id,
                    parse_mode="HTML"
                )
                return

            # Step 3: Animated Progress Bar - 100%
            try:
                bot_instance.edit_message_text(
                    f"🚀 <b>Uploading to Telegram...</b>\n"
                    f"[ ▰▰▰▰▰▰▰▰▰▰ ] <b>100%</b> • <i>Delivering media file!</i>",
                    chat_id,
                    status_msg_id,
                    parse_mode="HTML"
                )
            except Exception:
                pass

            with open(local_file, "rb") as f:
                if extract_audio:
                    try:
                        bot_instance.send_audio(
                            chat_id,
                            f,
                            title=title[:60],
                            caption=caption_text,
                            parse_mode="HTML",
                            timeout=180
                        )
                    except Exception:
                        f.seek(0)
                        bot_instance.send_document(
                            chat_id,
                            f,
                            caption=caption_text,
                            parse_mode="HTML",
                            timeout=180
                        )
                else:
                    try:
                        bot_instance.send_video(
                            chat_id,
                            f,
                            caption=caption_text,
                            parse_mode="HTML",
                            supports_streaming=True,
                            timeout=180
                        )
                    except Exception:
                        f.seek(0)
                        bot_instance.send_document(
                            chat_id,
                            f,
                            caption=caption_text,
                            parse_mode="HTML",
                            timeout=180
                        )
        else:
            if extract_audio:
                bot_instance.send_audio(chat_id, file_path, caption=caption_text, parse_mode="HTML")
            else:
                bot_instance.send_video(chat_id, file_path, caption=caption_text, parse_mode="HTML", supports_streaming=True)

        try:
            bot_instance.delete_message(chat_id, status_msg_id)
        except Exception:
            pass

    except Exception as exec_err:
        log_error(f"Execution error for {platform} download: {exec_err}")
        try:
            bot_instance.edit_message_text(
                f"❌ <b>Download Error:</b> <i>{escape(str(exec_err))}</i>",
                chat_id,
                status_msg_id,
                parse_mode="HTML"
            )
        except Exception:
            pass
    finally:
        if local_file and os.path.exists(local_file):
            try:
                os.remove(local_file)
            except Exception:
                pass

# ----------------- TELEGRAM BOT HANDLER REGISTRATION ----------------- #

def register_bot_handlers(bot_instance: telebot.TeleBot, is_clone: bool = False, clone_id: str | None = None):
    """Registers commands, callback queries, and message handlers on any bot instance."""

    def clone_is_disabled() -> bool:
        if is_clone and clone_id:
            if clone_id in STOPPED_CLONES:
                return True
            clones_db = load_data(CLONES_FILE)
            if clone_id not in clones_db:
                return True
            if clones_db.get(clone_id, {}).get("status") == "stopped":
                return True
        return False

    @bot_instance.callback_query_handler(func=lambda call: True)
    def handle_callback_query(call: telebot.types.CallbackQuery):
        if clone_is_disabled():
            return

        data = call.data or ""

        # Format: dl:v:<short_id> or dl:a:<short_id>
        if data.startswith("dl:"):
            parts = data.split(":")
            if len(parts) == 3:
                format_type = parts[1]
                short_id = parts[2]
                try:
                    bot_instance.answer_callback_query(call.id, text="🚀 Fetching media stream...")
                except Exception:
                    pass
                EXECUTOR.submit(
                    process_download_execution,
                    bot_instance,
                    call.message.chat.id,
                    call.message.message_id,
                    short_id,
                    format_type
                )
            return

        # Admin Clone Bot Actions
        if data.startswith("clone:"):
            if call.from_user.id != ADMIN_ID:
                try:
                    bot_instance.answer_callback_query(call.id, text="⚠️ Unauthorized action.", show_alert=True)
                except Exception:
                    pass
                return

            parts = data.split(":")
            if len(parts) == 3:
                action = parts[1]
                target_bot_id = parts[2]

                if action == "stop":
                    stop_cloned_bot(target_bot_id)
                    try:
                        bot_instance.answer_callback_query(call.id, text=f"🛑 Bot ID {target_bot_id} stopped!")
                        safe_reply(bot_instance, call.message, f"🛑 <b>Cloned Bot <code>{target_bot_id}</code> has been stopped and polling terminated.</b>", parse_mode="HTML")
                    except Exception:
                        pass

                elif action == "start":
                    start_cloned_bot(target_bot_id)
                    try:
                        bot_instance.answer_callback_query(call.id, text=f"▶️ Bot ID {target_bot_id} resumed!")
                        safe_reply(bot_instance, call.message, f"▶️ <b>Cloned Bot <code>{target_bot_id}</code> is resumed and polling active.</b>", parse_mode="HTML")
                    except Exception:
                        pass

                elif action == "del":
                    delete_cloned_bot(target_bot_id)
                    try:
                        bot_instance.answer_callback_query(call.id, text=f"🗑️ Bot ID {target_bot_id} deleted permanently!")
                        safe_reply(bot_instance, call.message, f"🗑️ <b>Cloned Bot <code>{target_bot_id}</code> removed permanently from database and stopped.</b>", parse_mode="HTML")
                    except Exception:
                        pass
            return

    # /start command handler
    @bot_instance.message_handler(commands=['start'])
    def handle_start(message: telebot.types.Message):
        if clone_is_disabled():
            return

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

        args = (message.text or "").split()
        ref_id = None
        if len(args) > 1 and args[1].isdigit():
            possible_ref = int(args[1])
            if possible_ref != message.chat.id:
                ref_id = possible_ref

        track_user_activity(message.from_user, "Start Command", message.text or "", referred_by=ref_id)

        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn_stats = types.KeyboardButton("📊 My Stats")
        btn_invite = types.KeyboardButton("👥 Invite Friends")
        btn_create = types.KeyboardButton("🤖 Create Own Bot")
        keyboard.row(btn_stats, btn_invite)
        keyboard.row(btn_create)

        # Clean, Short & Ultra-Modern Welcome Message
        welcome_text = (
            "⚡ <b>7G Ultimate Master Bot</b> 🚀\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📥 <b>Instant HD Downloader (No Watermarks):</b>\n"
            "• 📸 <b>Instagram:</b> Reels & Posts <i>(Full Audio Guarantee)</i>\n"
            "• 🎵 <b>TikTok:</b> Ultra HD Video & MP3 Audio\n"
            "• 🔴 <b>YouTube:</b> HD 1080p Videos & Shorts + MP3 Audio\n"
            "• 🔵 <b>Facebook:</b> HD Videos & Reels + MP3 Audio\n\n"
            "🤖 <b>AI Assistant Features:</b>\n"
            "• 💡 <b>Meta AI:</b> Chat directly or use <code>/ai &lt;query&gt;</code>\n"
            "• 🎨 <b>AI Images:</b> Create photos with <code>/image &lt;prompt&gt;</code>\n"
            "• 🤖 <b>Host Bot:</b> Tap <i>'Create Own Bot'</i> for 100% FREE cloning!\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "👉 <i>Send any link above to start downloading!</i>"
        )
        safe_reply(bot_instance, message, welcome_text, parse_mode="HTML", reply_markup=keyboard)

    # /mystats command handler (with Country / Nationality & Full Analytics)
    @bot_instance.message_handler(commands=['mystats'])
    def handle_my_stats(message: telebot.types.Message):
        if clone_is_disabled():
            return
        users_db = load_data(USER_FILE)
        uid = str(message.chat.id)
        uinfo = users_db.get(uid, {})

        first_seen = uinfo.get("first_seen", "N/A")
        last_seen = uinfo.get("last_seen", "N/A")
        msg_count = uinfo.get("msg_count", 1)
        dl_count = uinfo.get("downloads_count", 0)
        points = uinfo.get("points", 0)
        referrals = len(uinfo.get("referrals", []))
        nationality = uinfo.get("nationality") or (f"🌐 {escape(uinfo.get('language_code', 'en')).upper()} Region")

        stats_text = (
            f"📊 <b>YOUR BOT PROFILE & STATS</b> 🌟\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Name:</b> {escape(message.from_user.first_name)}\n"
            f"🔗 <b>Username:</b> @{escape(message.from_user.username) if message.from_user.username else 'No Username'}\n"
            f"🆔 <b>User ID:</b> <code>{message.chat.id}</code>\n"
            f"🌐 <b>Country / Region:</b> {nationality}\n"
            f"📅 <b>Joined Date:</b> <code>{first_seen}</code>\n"
            f"⏱️ <b>Last Activity:</b> <code>{last_seen}</code>\n"
            f"💬 <b>Messages Sent:</b> <code>{msg_count}</code>\n"
            f"📥 <b>Media Downloaded:</b> <code>{dl_count}</code>\n"
            f"👥 <b>Friends Invited:</b> <code>{referrals}</code>\n"
            f"🌟 <b>Reward Points:</b> <code>{points} pts</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Thank you for using 7G Master Bot!</i> ❤️"
        )
        safe_reply(bot_instance, message, stats_text, parse_mode="HTML")

    # /stats handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['stats'])
    def handle_admin_stats(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return

        users_db = load_data(USER_FILE)
        banned_db = load_data(BANNED_FILE)
        clones_db = load_data(CLONES_FILE)
        config = get_config()

        total_users = len(users_db)
        total_banned = len(banned_db) if isinstance(banned_db, list) else 0
        total_clones = len(clones_db) if isinstance(clones_db, dict) else 0
        maintenance = "🔴 ON" if config.get("maintenance", False) else "🟢 OFF"

        total_downloads = sum(u.get("downloads_count", 0) for u in users_db.values() if isinstance(u, dict))
        total_messages = sum(u.get("msg_count", 0) for u in users_db.values() if isinstance(u, dict))

        dashboard = (
            f"👑 <b>MASTER ADMIN DASHBOARD</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>Total Registered Users:</b> <code>{total_users}</code>\n"
            f"📥 <b>Total Media Downloads:</b> <code>{total_downloads}</code>\n"
            f"💬 <b>Total User Messages:</b> <code>{total_messages}</code>\n"
            f"🤖 <b>Total Cloned Bots:</b> <code>{total_clones}</code>\n"
            f"🚫 <b>Banned Users:</b> <code>{total_banned}</code>\n"
            f"🛠️ <b>Maintenance Mode:</b> <b>{maintenance}</b>\n"
            f"🕒 <b>Server Time:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <b>Commands:</b>\n"
            f"• <code>/clones</code> - Manage all cloned bots (Stop/Start/Delete)\n"
            f"• <code>/users</code> - List all registered users with country info\n"
            f"• <code>/userinfo &lt;id&gt;</code> - Inspect user history & links\n"
            f"• <code>/ban &lt;id&gt;</code> & <code>/unban &lt;id&gt;</code>\n"
            f"• <code>/broadcast &lt;text&gt;</code> - Global announcement\n"
            f"• <code>/maintenance</code> - Toggle maintenance (broadcasts on ON & OFF)\n"
            f"• <code>/restoredb</code> - Reply to a backup json to restore DB!"
        )
        safe_reply(bot_instance, message, dashboard, parse_mode="HTML")

    # /clones handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['clones', 'managebots'])
    def handle_clones_admin(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return

        clones_db = load_data(CLONES_FILE)
        if not isinstance(clones_db, dict) or not clones_db:
            safe_reply(bot_instance, message, "🤖 <b>No cloned bots created yet.</b>", parse_mode="HTML")
            return

        report = [
            f"🤖 <b>CLONED BOTS MANAGEMENT PANEL ({len(clones_db)} Bots)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ]

        markup = types.InlineKeyboardMarkup(row_width=2)

        for idx, (b_id, info) in enumerate(clones_db.items(), start=1):
            is_stopped = (info.get("status") == "stopped") or (b_id in STOPPED_CLONES)
            status_emoji = "🔴 STOPPED" if is_stopped else "🟢 ACTIVE"
            uname = info.get("username", "Unknown")
            owner_id = info.get("owner_id", "Unknown")
            owner_name = escape(info.get("owner_name", "Unknown"))
            created = info.get("created_at", "N/A")

            report.append(
                f"<b>{idx}. @{escape(uname)}</b> (ID: <code>{b_id}</code>)\n"
                f"   • Status: <b>{status_emoji}</b>\n"
                f"   • Owner: {owner_name} (<code>{owner_id}</code>)\n"
                f"   • Created: <code>{created}</code>"
            )

            if idx <= 8:
                toggle_btn = types.InlineKeyboardButton(
                    f"▶️ Start {uname[:7]}" if is_stopped else f"🛑 Stop {uname[:7]}",
                    callback_data=f"clone:{'start' if is_stopped else 'stop'}:{b_id}"
                )
                del_btn = types.InlineKeyboardButton(f"🗑️ Del", callback_data=f"clone:del:{b_id}")
                markup.add(toggle_btn, del_btn)

        report.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        report.append(
            "⚡ <b>Commands:</b>\n"
            "• <code>/stopbot &lt;bot_id&gt;</code> - Stop a specific bot\n"
            "• <code>/startbot &lt;bot_id&gt;</code> - Resume a stopped bot\n"
            "• <code>/delbot &lt;bot_id&gt;</code> - Delete a bot permanently"
        )

        full_output = "\n".join(report)
        chunk_and_send(bot_instance, message.chat.id, full_output, parse_mode="HTML")

    # /stopbot <bot_id> handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['stopbot'])
    def handle_stopbot(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return
        tokens = (message.text or "").split()
        if len(tokens) < 2:
            safe_reply(bot_instance, message, "⚠️ <b>Usage:</b> <code>/stopbot &lt;bot_id&gt;</code>", parse_mode="HTML")
            return
        target_id = tokens[1].strip()
        stop_cloned_bot(target_id)
        safe_reply(bot_instance, message, f"🛑 <b>Cloned Bot <code>{target_id}</code> has been stopped and polling terminated.</b>", parse_mode="HTML")

    # /startbot <bot_id> handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['startbot'])
    def handle_startbot(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return
        tokens = (message.text or "").split()
        if len(tokens) < 2:
            safe_reply(bot_instance, message, "⚠️ <b>Usage:</b> <code>/startbot &lt;bot_id&gt;</code>", parse_mode="HTML")
            return
        target_id = tokens[1].strip()
        start_cloned_bot(target_id)
        safe_reply(bot_instance, message, f"▶️ <b>Cloned Bot <code>{target_id}</code> is now resumed and active.</b>", parse_mode="HTML")

    # /delbot <bot_id> handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['delbot'])
    def handle_delbot(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return
        tokens = (message.text or "").split()
        if len(tokens) < 2:
            safe_reply(bot_instance, message, "⚠️ <b>Usage:</b> <code>/delbot &lt;bot_id&gt;</code>", parse_mode="HTML")
            return
        target_id = tokens[1].strip()
        delete_cloned_bot(target_id)
        safe_reply(bot_instance, message, f"🗑️ <b>Cloned Bot <code>{target_id}</code> removed permanently from database and stopped.</b>", parse_mode="HTML")

    # /restoredb handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['restoredb', 'restoreusers'])
    def handle_restore_db(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return

        doc = None
        if message.reply_to_message and message.reply_to_message.document:
            doc = message.reply_to_message.document
        elif message.document:
            doc = message.document

        if not doc:
            safe_reply(
                bot_instance,
                message,
                "⚠️ <b>How to Restore:</b> Reply to any backup JSON file (e.g. <code>users_db.json</code>) with <code>/restoredb</code>!",
                parse_mode="HTML"
            )
            return

        try:
            file_info = bot_instance.get_file(doc.file_id)
            downloaded = bot_instance.download_file(file_info.file_path)
            content = json.loads(downloaded.decode("utf-8"))

            if isinstance(content, dict):
                first_val = next(iter(content.values()), {})
                if isinstance(first_val, dict) and "first_seen" in first_val:
                    with FILE_LOCK:
                        existing = load_data(USER_FILE)
                        if isinstance(existing, dict):
                            existing.update(content)
                            save_data(USER_FILE, existing)
                        else:
                            save_data(USER_FILE, content)
                    safe_reply(bot_instance, message, f"✅ <b>Successfully restored {len(content)} users into database!</b>", parse_mode="HTML")
                elif isinstance(first_val, dict) and "token" in first_val:
                    with FILE_LOCK:
                        save_data(CLONES_FILE, content)
                    restore_saved_clones()
                    safe_reply(bot_instance, message, f"✅ <b>Successfully restored {len(content)} cloned bots into database!</b>", parse_mode="HTML")
                else:
                    safe_reply(bot_instance, message, "⚠️ Unrecognized JSON format.", parse_mode="HTML")
        except Exception as rest_err:
            log_error(f"Failed to restore DB: {rest_err}")
            safe_reply(bot_instance, message, f"❌ <b>Restore Failed:</b> <i>{escape(str(rest_err))}</i>", parse_mode="HTML")

    # /users handler (ADMIN ONLY)
    @bot_instance.message_handler(commands=['users'])
    def handle_admin_users(message: telebot.types.Message):
        if message.chat.id != ADMIN_ID:
            return

        users_db = load_data(USER_FILE)
        if not isinstance(users_db, dict) or not users_db:
            safe_reply(bot_instance, message, "❌ <b>No users registered in database.</b>", parse_mode="HTML")
            return

        lines = [
            f"📋 <b>ALL REGISTERED USERS DIRECTORY ({len(users_db)} Users)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ]

        sorted_users = sorted(
            users_db.items(),
            key=lambda x: x[1].get("last_seen", ""),
            reverse=True
        )

        for idx, (uid, info) in enumerate(sorted_users, start=1):
            name = escape(info.get("first_name", "Unknown"))
            uname = escape(info.get("username", "No Username"))
            nationality = escape(info.get("nationality", "N/A"))
            downloads = info.get("downloads_count", 0)
            msgs = info.get("msg_count", 0)
            last = info.get("last_seen", "N/A")

            lines.append(
                f"<b>{idx}. {name}</b> ({uname})\n"
                f"   • ID: <code>{uid}</code> | Country: {nationality}\n"
                f"   • Msgs: <code>{msgs}</code> | DLs: <code>{downloads}</code> | Active: <code>{last}</code>"
            )

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 <i>Use /userinfo &lt;user_id&gt; to view complete user history and links.</i>")

        full_output = "\n".join(lines)
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
        nationality = escape(info.get("nationality", "N/A"))
        msg_count = info.get("msg_count", 0)
        dl_count = info.get("downloads_count", 0)
        first_seen = info.get("first_seen", "N/A")
        last_seen = info.get("last_seen", "N/A")
        referred_by = info.get("referred_by") or "None (Direct)"
        referrals = info.get("referrals", [])
        points = info.get("points", 0)

        messages_list = info.get("messages", [])
        if messages_list:
            serialized_msgs = "\n".join(
                [f"  {i}. \"{escape(m)}\"" for i, m in enumerate(messages_list[-25:], start=1)]
            )
        else:
            serialized_msgs = "  <i>(No text messages recorded)</i>"

        links_list = info.get("download_links", [])
        if links_list:
            serialized_links = "\n".join(
                [f"  {i}. <code>{escape(l)}</code>" for i, l in enumerate(links_list[-25:], start=1)]
            )
        else:
            serialized_links = "  <i>(No downloaded links recorded)</i>"

        details = (
            f"🔍 <b>DETAILED USER PROFILE & ACTIVITY LOG</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Name:</b> {name}\n"
            f"🔗 <b>Username:</b> {uname}\n"
            f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
            f"🌐 <b>Country:</b> {nationality}\n"
            f"📅 <b>Joined Date:</b> <code>{first_seen}</code>\n"
            f"⏱️ <b>Last Activity:</b> <code>{last_seen}</code>\n"
            f"👥 <b>Referred By:</b> <code>{referred_by}</code>\n"
            f"🎯 <b>Invited Users Count:</b> <code>{len(referrals)}</code>\n"
            f"🌟 <b>Reward Points:</b> <code>{points} pts</code>\n"
            f"💬 <b>Total Messages:</b> <code>{msg_count}</code>\n"
            f"📥 <b>Total Downloads:</b> <code>{dl_count}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💬 <b>RECENT MESSAGES (LAST 25):</b>\n{serialized_msgs}\n\n"
            f"🔗 <b>DOWNLOADED LINKS (LAST 25):</b>\n{serialized_links}\n"
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
            EXECUTOR.submit(broadcast_maintenance_notice, message.chat.id, True)
        else:
            safe_reply(
                bot_instance,
                message,
                "✅ <b>Maintenance mode turned OFF! Broadcasting completion notice to all registered users...</b>",
                parse_mode="HTML"
            )
            EXECUTOR.submit(broadcast_maintenance_notice, message.chat.id, False)

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
        if clone_is_disabled():
            return

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

        if text == "📊 My Stats":
            handle_my_stats(message)
            return

        # "👥 Invite Friends" Button
        elif text == "👥 Invite Friends" or text == "🔗 Referral Link" or text == "🚀 Share Trendy":
            try:
                me = bot_instance.get_me()
                ref_link = f"https://t.me/{me.username}?start={message.chat.id}"
                invite_card = (
                    f"👥 <b>INVITE FRIENDS & EARN REWARDS</b> 🌟\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔗 <b>Your Personal Invite Link:</b>\n"
                    f"<code>{ref_link}</code>\n\n"
                    f"💡 <b>Reward System:</b>\n"
                    f"• Share this link with friends and groups.\n"
                    f"• Earn <b>+10 Reward Points</b> for every new user who joins!\n"
                    f"• Track your invited friends anytime in <b>📊 My Stats</b>."
                )
                safe_reply(bot_instance, message, invite_card, parse_mode="HTML")
            except Exception:
                safe_reply(bot_instance, message, f"🔗 <b>Your Invite ID:</b> <code>{message.chat.id}</code>", parse_mode="HTML")
            return

        elif text == "🤖 Create Own Bot" or text == "/createbot":
            if is_clone:
                safe_reply(bot_instance, message, "⚠️ <i>This cloned bot cannot create further sub-bots.</i>", parse_mode="HTML")
                return

            AWAITING_BOT_TOKEN.add(message.chat.id)
            prompt_text = (
                "🤖 <b>Create & Host Your Own Bot For FREE!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "1. Go to @BotFather on Telegram.\n"
                "2. Create a new bot with <code>/newbot</code> and copy your <b>Bot Token</b>.\n"
                "3. <b>Paste and send your Bot Token directly here in this chat!</b>\n\n"
                "⚡ <i>Your personal bot will instantly go LIVE with Instagram, TikTok HD, YouTube, Facebook & AI features!</i>"
            )
            safe_reply(bot_instance, message, prompt_text, parse_mode="HTML")
            return

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

        # ----------------- LINK DETECTION WITH INTERACTIVE CHOICES ----------------- #

        # 1. Instagram Link Detection (Reels, Posts, Stories)
        if "instagram.com" in text.lower():
            url_match = re.search(r"https?://[^\s]+", text)
            clean_link = url_match.group(0) if url_match else text
            track_user_activity(message.from_user, "Instagram Download", clean_link)
            prompt_media_choice(bot_instance, message, clean_link, "instagram")
            return

        # 2. TikTok Link Detection (Normal, vm, vt)
        if "tiktok.com" in text.lower() or "vt.tiktok.com" in text.lower():
            url_match = re.search(r"https?://[^\s]+", text)
            clean_link = url_match.group(0) if url_match else text
            track_user_activity(message.from_user, "TikTok Download", clean_link)
            prompt_media_choice(bot_instance, message, clean_link, "tiktok")
            return

        # 3. YouTube Link Detection (Videos, Shorts, youtu.be)
        if "youtube.com" in text.lower() or "youtu.be" in text.lower():
            url_match = re.search(r"https?://[^\s]+", text)
            clean_link = url_match.group(0) if url_match else text
            track_user_activity(message.from_user, "YouTube Download", clean_link)
            prompt_media_choice(bot_instance, message, clean_link, "youtube")
            return

        # 4. Facebook Link Detection (Videos, Reels, Watch, fb.gg)
        if "facebook.com" in text.lower() or "fb.watch" in text.lower() or "fb.gg" in text.lower():
            url_match = re.search(r"https?://[^\s]+", text)
            clean_link = url_match.group(0) if url_match else text
            track_user_activity(message.from_user, "Facebook Download", clean_link)
            prompt_media_choice(bot_instance, message, clean_link, "facebook")
            return

        # 5. General Text -> Meta AI Assistant (No Song Search)
        track_user_activity(message.from_user, "General Chat / AI Query", text)
        status_msg = bot_instance.reply_to(message, "💭 <i>Thinking...</i>", parse_mode="HTML")
        EXECUTOR.submit(send_ai_response, bot_instance, message.chat.id, text, status_msg.message_id)

# ----------------- BROADCAST & MAINTENANCE ENGINES ----------------- #

def broadcast_maintenance_notice(admin_chat_id: int, is_maintenance_on: bool) -> None:
    if is_maintenance_on:
        notice_text = (
            "⚠️ <b>Notice:</b> The bot is currently undergoing system security updates and maintenance. "
            "It is temporarily unavailable. Please try again later! 🛠️"
        )
    else:
        notice_text = (
            "✅ <b>Notice:</b> System maintenance is completed! "
            "The bot is now fully online, unlocked, and ready for you to use. Enjoy! 🚀✨"
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
            bot.send_message(uid, notice_text, parse_mode="HTML")
            sent += 1
            time.sleep(0.04)
        except Exception:
            failed += 1

    mode_label = "TURNED ON" if is_maintenance_on else "TURNED OFF"
    try:
        bot.send_message(
            admin_chat_id,
            f"📢 <b>Maintenance Notice ({mode_label}) Broadcast Completed:</b>\n"
            f"✅ Sent: <code>{sent}</code>\n"
            f"⚠️ Failed/Blocked: <code>{failed}</code>",
            parse_mode="HTML"
        )
    except Exception:
        pass

def execute_broadcast(admin_chat_id: int, text: str) -> None:
    users_db = load_data(USER_FILE)
    sent = 0
    failed = 0

    broadcast_payload = (
        f"📢 <b>OFFICIAL ANNOUNCEMENT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{escape(text)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    for uid in users_db.keys():
        try:
            bot.send_message(uid, broadcast_payload, parse_mode="HTML")
            sent += 1
            time.sleep(0.04)
        except Exception:
            failed += 1

    try:
        bot.send_message(
            admin_chat_id,
            f"📢 <b>Broadcast Completed!</b>\n"
            f"✅ Successfully Delivered: <code>{sent}</code>\n"
            f"⚠️ Failed/Blocked: <code>{failed}</code>",
            parse_mode="HTML"
        )
    except Exception:
        pass

# ----------------- 'CREATE OWN BOT' MULTI-BOT SYSTEM ----------------- #

def stop_cloned_bot(bot_id: str) -> None:
    STOPPED_CLONES.add(bot_id)
    with FILE_LOCK:
        clones_db = load_data(CLONES_FILE)
        if bot_id in clones_db:
            clones_db[bot_id]["status"] = "stopped"
            save_data(CLONES_FILE, clones_db)

    if bot_id in ACTIVE_CLONES:
        try:
            ACTIVE_CLONES[bot_id].stop_polling()
            log(f"Stopped polling for cloned bot ID: {bot_id}")
        except Exception as stop_err:
            log_error(f"Error stopping polling for bot {bot_id}: {stop_err}")

def start_cloned_bot(bot_id: str) -> bool:
    STOPPED_CLONES.discard(bot_id)
    with FILE_LOCK:
        clones_db = load_data(CLONES_FILE)
        if bot_id not in clones_db:
            return False
        clones_db[bot_id]["status"] = "active"
        save_data(CLONES_FILE, clones_db)
        token = clones_db[bot_id].get("token")
        username = clones_db[bot_id].get("username", "Unknown")

    if not token:
        return False

    try:
        clone_bot = telebot.TeleBot(token, parse_mode=None)
        try:
            clone_bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass
        register_bot_handlers(clone_bot, is_clone=True, clone_id=bot_id)
        ACTIVE_CLONES[bot_id] = clone_bot
        t = threading.Thread(target=run_clone_polling, args=(clone_bot, username, bot_id), daemon=True)
        t.start()
        log(f"Started polling for cloned bot @{username} (ID: {bot_id})")
        return True
    except Exception as start_err:
        log_error(f"Failed to start bot {bot_id}: {start_err}")
        return False

def delete_cloned_bot(bot_id: str) -> None:
    stop_cloned_bot(bot_id)
    with FILE_LOCK:
        clones_db = load_data(CLONES_FILE)
        if bot_id in clones_db:
            del clones_db[bot_id]
            save_data(CLONES_FILE, clones_db)
    ACTIVE_CLONES.pop(bot_id, None)

def launch_user_clone_bot(message: telebot.types.Message, token: str):
    try:
        test_bot = telebot.TeleBot(token, parse_mode=None)
        me = test_bot.get_me()
        bot_username = me.username
        bot_id = str(me.id)

        try:
            test_bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass

        register_bot_handlers(test_bot, is_clone=True, clone_id=bot_id)

        with FILE_LOCK:
            clones_db = load_data(CLONES_FILE)
            if not isinstance(clones_db, dict):
                clones_db = {}
            clones_db[bot_id] = {
                "token": token,
                "username": bot_username,
                "owner_id": message.chat.id,
                "owner_name": message.from_user.first_name,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "active"
            }
            save_data(CLONES_FILE, clones_db, trigger_backup=False)

        ACTIVE_CLONES[bot_id] = test_bot
        STOPPED_CLONES.discard(bot_id)
        t = threading.Thread(target=run_clone_polling, args=(test_bot, bot_username, bot_id), daemon=True)
        t.start()

        success_msg = (
            f"🎉 <b>CONGRATULATIONS! YOUR BOT IS NOW LIVE!</b> 🚀\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <b>Bot Username:</b> @{bot_username}\n"
            f"🆔 <b>Bot ID:</b> <code>{bot_id}</code>\n"
            f"⚡ <b>Status:</b> 100% Online & Hosted 24/7!\n\n"
            f"👉 <b>Open your bot now:</b> https://t.me/{bot_username}\n"
            f"<i>Your bot has Instagram, TikTok HD, YouTube, Facebook & AI features active right now!</i>"
        )
        safe_reply(bot, message, success_msg, parse_mode="HTML")

        bot.send_message(
            ADMIN_ID,
            f"🤖 <b>New Bot Cloned!</b>\nOwner: <code>{message.chat.id}</code> ({message.from_user.first_name})\nBot: @{bot_username} (ID: <code>{bot_id}</code>)",
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

def run_clone_polling(clone_bot: telebot.TeleBot, username: str, bot_id: str):
    log(f"Cloned bot @{username} polling initialized.")
    while True:
        if bot_id in STOPPED_CLONES:
            log(f"Clone polling loop exiting for stopped bot ID: {bot_id}")
            break
        with FILE_LOCK:
            clones_db = load_data(CLONES_FILE)
            if bot_id not in clones_db or clones_db.get(bot_id, {}).get("status") == "stopped":
                log(f"Clone polling loop exiting for bot ID: {bot_id} (marked stopped or deleted)")
                break
        try:
            clone_bot.infinity_polling(timeout=30, long_polling_timeout=20, skip_pending=True)
        except Exception as err:
            if bot_id in STOPPED_CLONES:
                break
            log_error(f"Cloned bot @{username} polling error: {err}. Reconnecting in 10s...")
            time.sleep(10)

def restore_saved_clones():
    clones_db = load_data(CLONES_FILE)
    if isinstance(clones_db, dict) and clones_db:
        log(f"Restoring {len(clones_db)} cloned bots from database...")
        for bot_id, item in clones_db.items():
            token = item.get("token")
            username = item.get("username", "UnknownBot")
            status = item.get("status", "active")
            if status == "stopped":
                STOPPED_CLONES.add(bot_id)
                log(f"Cloned bot @{username} is marked STOPPED; skipping launch.")
                continue

            if token and bot_id not in STOPPED_CLONES:
                try:
                    clone_bot = telebot.TeleBot(token, parse_mode=None)
                    try:
                        clone_bot.delete_webhook(drop_pending_updates=True)
                    except Exception:
                        pass
                    register_bot_handlers(clone_bot, is_clone=True, clone_id=bot_id)
                    ACTIVE_CLONES[bot_id] = clone_bot
                    t = threading.Thread(target=run_clone_polling, args=(clone_bot, username, bot_id), daemon=True)
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
