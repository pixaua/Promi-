
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

LOG = logging.getLogger("streamly")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

# ----------------- CONFIGURATION ----------------- #
BOT_TOKEN = "7678905793:AAGNMxC34F2dQ8bgojFAyGApeHA20Yk_8gI"  # New Telegram Bot Token
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

@app.route('/')
def home():
    return "✨ 7G Master Bot is Online & Running!"

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

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
        
        if "users_db.json" in filepath:
            try:
                with open(filepath, "rb") as bf:
                    bot.send_document(ADMIN_ID, bf, caption="🛡️ *Auto Telegram Database Backup Sync* ✨", parse_mode="Markdown")
            except Exception:
                pass
    except Exception as e:
        LOG.error(f"Data Save Error: {e}")

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
            "download_links": [text_data] if text_data else [],
            "referred_by": referred_by,
            "referrals": [],
            "points": 0
        }
        if referred_by and referred_by in users_db and referred_by != user_id:
            users_db[referred_by]["referrals"].append(user_id)
            users_db[referred_by]["points"] = users_db[referred_by].get("points", 0) + 1
    else:
        users_db[user_id]["last_seen"] = now_str
        users_db[user_id]["msg_count"] += 1
        if user.first_name:
            users_db[user_id]["first_name"] = user.first_name
        if user.username:
            users_db[user_id]["username"] = f"@{user.username}"
        if user.language_code:
            users_db[user_id]["language_code"] = user.language_code
        
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
            f"🌐 *Lang:* `{user_info['language_code']}`\n"
            f"📅 *First Seen:* `{user_info['first_seen']}`\n"
            f"🕒 *Last Seen:* `{user_info['last_seen']}`\n"
            f"💬 *Total Messages:* `{user_info['msg_count']}`\n"
            f"📥 *Total Downloads:* `{user_info['downloads_count']}`\n"
            f"⚡ *Action:* {action_type}\n"
            f"📌 *Data/Text:* {text_data}\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(ADMIN_ID, alert_msg, parse_mode="Markdown")
    except Exception as e:
        LOG.error(f"Admin Alert Error: {e}")

# ----------------- DOWNLOAD ENGINES ----------------- #
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
    return None

def download_tiktok(url):
    try:
        api_url = f"https://www.tikwm.com/api/?url={url}"
        res = requests.get(api_url, timeout=15).json()
        if res.get("code") == 0 and "data" in res:
            data = res["data"]
            if "play" in data:
                return data["play"]
            elif "hdplay" in data:
                return data["hdplay"]
    except Exception:
        pass
    return None

# ----------------- META AI CHAT ----------------- #
def ask_meta_ai(prompt: str) -> str:
    try:
        payload = json.dumps({"prompt": prompt, "chat_history": []}).encode("utf-8")
        req = Request(
            META_AI_ENDPOINT,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {META_AI_KEY}",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        with urlopen(req, timeout=40) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            res = json.loads(raw)
            if isinstance(res, dict):
                answer = res.get("response") or res.get("result") or res.get("message")
                if answer:
                    return str(answer)
    except Exception as e:
        LOG.error(f"Meta AI Error: {e}")
    return "I am currently unable to process your request via Meta AI. Please try again later!"

# ----------------- BOT COMMANDS ----------------- #
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "❌ *You are banned from using this bot!*", parse_mode="Markdown")
        return

    config = get_config()
    if config.get("maintenance", False) and message.chat.id != ADMIN_ID:
        bot.reply_to(message, "🛠️ *Bot is under maintenance! The bot is currently unavailable and will be back soon.*", parse_mode="Markdown")
        return

    args = message.text.split()
    referred_by = args[1] if len(args) > 1 else None

    track_user_activity(message.from_user, "Start Command", message.text, referred_by)

    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        telebot.types.KeyboardButton("📊 My Stats"),
        telebot.types.KeyboardButton("🔗 Referral Link"),
        telebot.types.KeyboardButton("🤖 AI Chat"),
        telebot.types.KeyboardButton("🚀 Create Own Bot")
    )

    welcome_text = (
        "✨🔥 *Welcome to 7G Ultimate Master Bot!* 🔥✨\n\n"
        "📥 *Instagram & TikTok:* Send any link for instant HD download!\n"
        "🤖 *AI Chat:* Chat with Meta AI assistant anytime.\n\n"
        "👇 *Use the bottom menu for quick options!*"
    )
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['mystats'])
def user_stats(message):
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
        f"📊 *Your Personal Bot Statistics* 🌟\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 *Joined Date:* `{first_seen}`\n"
        f"💬 *Total Messages Sent:* `{msgs}`\n"
        f"📥 *Total Videos Downloaded:* `{downloads}`\n"
        f"👥 *Total Referrals:* `{refs}` (Points: `{points}`)\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    bot.reply_to(message, stats_msg, parse_mode="Markdown")

@bot.message_handler(commands=['stats', 'users'])
def show_stats(message):
    if message.chat.id != ADMIN_ID:
        return

    users_db = load_data(USER_FILE)
    total_users = len(users_db)
    total_downloads = sum(u.get("downloads_count", 0) for u in users_db.values())

    user_summaries = []
    for uid, info in users_db.items():
        links = info.get("download_links", [])
        if links:
            links_str = "\n".join([f"   • `{l}`" for l in links[-15:]])
        else:
            links_str = "   • No activity recorded."
            
        user_summaries.append(
            f"👤 *Name:* {info.get('first_name')} (ID: `{uid}`)\n"
            f"🔗 *Username:* {info.get('username')}\n"
            f"📥 *Downloads:* `{info.get('downloads_count')}` | 💬 *Msgs:* `{info.get('msg_count')}`\n"
            f"📌 *User Activity/Links History:*\n{links_str}\n"
            f"----------------------------------------"
        )
    
    users_text = "\n\n".join(user_summaries) if user_summaries else "No user records found."
    
    if len(users_text) > 3800:
        chunks = [users_text[i:i+3800] for i in range(0, len(users_text), 3800)]
        bot.reply_to(message, f"📊 *Admin Dashboard Statistics*\n👥 *Total Users:* `{total_users}`\n📥 *Total Downloads:* `{total_downloads}`", parse_mode="Markdown")
        for chunk in chunks:
            bot.send_message(ADMIN_ID, chunk, parse_mode="Markdown")
    else:
        stats_text = (
            f"📊 *Admin Dashboard Statistics*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 *Total Users:* `{total_users}`\n"
            f"📥 *Total Downloads:* `{total_downloads}`\n\n"
            f"📋 *All Users & Their Activity History:*\n\n{users_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        bot.reply_to(message, stats_text, parse_mode="Markdown")

@bot.message_handler(commands=['userinfo'])
def specific_user_info(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        target_id = message.text.split()[1]
        users_db = load_data(USER_FILE)
        if target_id in users_db:
            info = users_db[target_id]
            links = info.get('download_links', [])
            links_str = "\n".join([f"• `{l}`" for l in links]) if links else "No history yet."
            if len(links_str) > 3000:
                links_str = links_str[:3000] + "\n... (truncated)"

            info_text = (
                f"👤 *User Detailed History*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📛 Name: {info.get('first_name')}\n"
                f"🔗 Username: {info.get('username')}\n"
                f"🆔 ID: `{target_id}`\n"
                f"🌐 Lang: `{info.get('language_code')}`\n"
                f"📅 First Seen: `{info.get('first_seen')}`\n"
                f"🕒 Last Seen: `{info.get('last_seen')}`\n"
                f"💬 Messages: `{info.get('msg_count')}`\n"
                f"📥 Total Downloads: `{info.get('downloads_count')}`\n\n"
                f"🔗 *Full Activity & Message History:*\n{links_str}\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            bot.reply_to(message, info_text, parse_mode="Markdown")
        else:
            bot.reply_to(message, "❌ *User ID not found in database.*", parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, "⚠️ *Usage:* `/userinfo <user_id>`", parse_mode="Markdown")

@bot.message_handler(commands=['maintenance'])
def toggle_maintenance(message):
    if message.chat.id != ADMIN_ID:
        return
    config = get_config()
    current = config.get("maintenance", False)
    config["maintenance"] = not current
    save_data(CONFIG_FILE, config)
    
    status = "ON 🛠️ (Bot is now locked for users)" if config["maintenance"] else "OFF ✅ (Bot is now running for everyone)"
    bot.reply_to(message, f"🛠️ *Maintenance Mode is now {status}*", parse_mode="Markdown")

    if config["maintenance"]:
        users_db = load_data(USER_FILE)
        for uid in users_db.keys():
            try:
                bot.send_message(
                    uid, 
                    "⚠️ *Notice:* The bot is currently undergoing maintenance and will be temporarily unavailable. We will be back online soon!", 
                    parse_mode="Markdown"
                )
            except Exception:
                pass

@bot.message_handler(commands=['ban'])
def ban_user(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        target_id = str(message.text.split()[1])
        banned_list = load_data(BANNED_FILE)
        if not isinstance(banned_list, list):
            banned_list = []
        if target_id not in [str(u) for u in banned_list]:
            banned_list.append(target_id)
            save_data(BANNED_FILE, banned_list)
            bot.reply_to(message, f"✅ *User ID `{target_id}` has been successfully banned!*", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"⚠️ *User ID `{target_id}` is already in the ban list.*", parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, "⚠️ *Usage:* `/ban <user_id>`", parse_mode="Markdown")

@bot.message_handler(commands=['unban'])
def unban_user(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        target_id = str(message.text.split()[1])
        banned_list = load_data(BANNED_FILE)
        if not isinstance(banned_list, list):
            banned_list = []
        banned_list = [str(u) for u in banned_list]
        if target_id in banned_list:
            banned_list.remove(target_id)
            save_data(BANNED_FILE, banned_list)
            bot.reply_to(message, f"✅ *User ID `{target_id}` has been unbanned!*", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"⚠️ *User ID `{target_id}` was not banned.*", parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, "⚠️ *Usage:* `/unban <user_id>`", parse_mode="Markdown")

@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    if message.chat.id != ADMIN_ID:
        return

    msg_to_send = message.text.replace("/broadcast", "").strip()
    if not msg_to_send:
        bot.reply_to(message, "⚠️ *Usage:* `/broadcast Your message here`", parse_mode="Markdown")
        return

    users_db = load_data(USER_FILE)
    if not users_db:
        bot.reply_to(message, "❌ *No users found in database.*", parse_mode="Markdown")
        return

    sent = 0
    failed = 0
    for uid in users_db.keys():
        try:
            bot.send_message(uid, f"📢 *Admin Announcement:*\n\n{msg_to_send}", parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1

    bot.reply_to(message, f"✅ *Broadcast Finished!*\n🟢 Sent: `{sent}`\n🔴 Failed: `{failed}`", parse_mode="Markdown")

# ----------------- GENERAL MESSAGE & MENU HANDLER ----------------- #
AI_ACTIVE_CHATS: set[int] = set()

@bot.message_handler(func=lambda message: True)
def process_message(message):
    if is_banned(message.chat.id):
        bot.reply_to(message, "❌ *You are banned from using this bot!*", parse_mode="Markdown")
        return

    config = get_config()
    if config.get("maintenance", False) and message.chat.id != ADMIN_ID:
        bot.reply_to(message, "🛠️ *Bot is under maintenance! Please try again later.*", parse_mode="Markdown")
        return

    text = message.text.strip()
    chat_id = message.chat.id

    # Track every single message sent by the user into database
    track_user_activity(message.from_user, "User Message Sent", text)

    if text == "📊 My Stats":
        user_stats(message)
        return
    elif text == "🔗 Referral Link":
        bot_username = bot.get_me().username
        ref_link = f"https://t.me/{bot_username}?start={chat_id}"
        bot.reply_to(message, f"👥 *Your Personal Referral Link:*\n`{ref_link}`\n\n_Share this link with your friends to invite them!_ ✨", parse_mode="Markdown")
        return
    elif text == "🤖 AI Chat":
        AI_ACTIVE_CHATS.add(chat_id)
        bot.reply_to(message, "🤖 *Meta AI Chat Mode Activated!*\n\nNow you can type anything and I will reply using Meta AI. Send /start or any download link to exit AI mode.", parse_mode="Markdown")
        return
    elif text == "🚀 Create Own Bot":
        bot.reply_to(message, "🚀 *Create Your Own Bot Service*\n\nIf you want to deploy your own custom bot using your Telegram Bot Token, please contact the admin (@abirboos721) for setup and details!", parse_mode="Markdown")
        return

    if chat_id in AI_ACTIVE_CHATS:
        if text.lower() in ["/start", "/cancel", "exit"]:
            AI_ACTIVE_CHATS.discard(chat_id)
            bot.reply_to(message, "✅ *Exited AI Chat Mode.*", parse_mode="Markdown")
            return
        
        status_msg = bot.reply_to(message, "🤖 *Meta AI is thinking...*", parse_mode="Markdown")
        ai_response = ask_meta_ai(text)
        try:
            bot.edit_message_text(ai_response, chat_id, status_msg.message_id, parse_mode="Markdown")
        except Exception:
            bot.send_message(chat_id, ai_response, parse_mode="Markdown")
            try:
                bot.delete_message(chat_id, status_msg.message_id)
            except Exception:
                pass
        return

    # Instagram Handling
    if "instagram.com" in text.lower():
        status_msg = bot.reply_to(message, "⏳ *Downloading Instagram media, please hold on...* 🚀", parse_mode="Markdown")
        video_url = download_instagram(text)
        if video_url:
            try:
                bot.send_video(chat_id, video_url, caption="📥 *Downloaded via 7G Master Bot*", parse_mode="Markdown")
                bot.delete_message(chat_id, status_msg.message_id)
            except Exception:
                bot.edit_message_text("❌ *Video file is too large or failed to send.*", chat_id, status_msg.message_id, parse_mode="Markdown")
        else:
            bot.edit_message_text("❌ *Failed to fetch Instagram media. Try another link!*", chat_id, status_msg.message_id, parse_mode="Markdown")

    # TikTok Handling
    elif "tiktok.com" in text.lower() or "vt.tiktok.com" in text.lower():
        status_msg = bot.reply_to(message, "⏳ *Downloading TikTok video without watermark...* 🎵", parse_mode="Markdown")
        video_url = download_tiktok(text)
        if video_url:
            try:
                bot.send_video(chat_id, video_url, caption="📥 *Downloaded via 7G Master Bot*", parse_mode="Markdown")
                bot.delete_message(chat_id, status_msg.message_id)
            except Exception:
                bot.edit_message_text("❌ *Video file is too large or failed to send.*", chat_id, status_msg.message_id, parse_mode="Markdown")
        else:
            bot.edit_message_text("❌ *Failed to fetch TikTok video. Try another link!*", chat_id, status_msg.message_id, parse_mode="Markdown")

    else:
        bot.reply_to(message, "⚠️ *Message received and saved! Send a valid Instagram/TikTok link or use '🤖 AI Chat'.* 📌", parse_mode="Markdown")

# ----------------- MAIN RUNNER ----------------- #
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    LOG.info("Bot polling started successfully...")
    bot.infinity_polling()
