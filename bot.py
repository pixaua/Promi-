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
BOT_TOKEN = "7678905793:AAGNMxC34F2dQ8bgojFAyGApeHA20Yk_8gI"  # Main Bot Token
ADMIN_ID = 6162953772                # Admin User ID
META_AI_KEY = os.getenv("META_AI_API_KEY", "nxt_3a454c41e6a84aeead28d1fb4aec87a4").strip()

META_AI_GEM_ID = "ba0fbe0d-976e-493a-afdb-6d8469e53df0"
META_AI_ENDPOINT = f"https://nxtai.zipohostbd.workers.dev/api/use?gem={META_AI_GEM_ID}"
TIKWM_ENDPOINT = "https://www.tikwm.com/api/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
USER_FILE = os.path.join(DATA_DIR, "users_db.json")
BANNED_FILE = os.path.join(DATA_DIR, "banned_users.json")
CONFIG_FILE = os.path.join(DATA_DIR, "bot_config.json")
CLONED_BOTS_FILE = os.path.join(DATA_DIR, "cloned_bots.json")

main_bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

RUNNING_CLONES = {}
AI_ACTIVE_CHATS: set[int] = set()

@app.route('/')
def home():
    return "✨ 7G Master Multi-Bot Service is Online & Running!"

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
                    main_bot.send_document(ADMIN_ID, bf, caption="🛡️ *Auto Telegram Database Backup Sync* ✨", parse_mode="Markdown")
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
        main_bot.send_message(ADMIN_ID, alert_msg, parse_mode="Markdown")
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

# ----------------- META AI CHAT ENGINE ----------------- #
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
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            res = json.loads(raw)
            if isinstance(res, dict):
                answer = res.get("response") or res.get("result") or res.get("message")
                if answer:
                    return str(answer)
    except Exception as e:
        LOG.error(f"Meta AI Error: {e}")
    return f"Hello! How can I assist you today? Feel free to send me any question or download link!"

# ----------------- BOT HANDLERS LOGIC ----------------- #
def setup_bot_handlers(target_bot: telebot.TeleBot, is_clone=False):
    
    @target_bot.message_handler(commands=['start'])
    def send_welcome(message):
        if is_banned(message.chat.id):
            target_bot.reply_to(message, "❌ *You are banned from using this bot!*", parse_mode="Markdown")
            return

        config = get_config()
        if config.get("maintenance", False) and message.chat.id != ADMIN_ID:
            target_bot.reply_to(message, "🛠️ *Bot is under maintenance! Please try again later.*", parse_mode="Markdown")
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
            "✨🔥 *Welcome to Ultimate Master Bot!* 🔥✨\n\n"
            "📥 *Instagram & TikTok:* Send any link for instant HD download!\n"
            "🤖 *AI Chat:* Click '🤖 AI Chat' or type anything to chat!\n"
            "🚀 *Create Own Bot:* Send your Telegram bot token to host your bot live instantly!\n\n"
            "👇 *Use the bottom menu for quick options!*"
        )
        target_bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

    @target_bot.message_handler(commands=['mystats'])
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
        target_bot.reply_to(message, stats_msg, parse_mode="Markdown")

    @target_bot.message_handler(commands=['stats', 'users'])
    def show_stats(message):
        if message.chat.id != ADMIN_ID:
            return

        users_db = load_data(USER_FILE)
        total_users = len(users_db)
        total_downloads = sum(u.get("downloads_count", 0) for u in users_db.values())

        user_summaries = []
        for uid, info in users_db.items():
            links = info.get("download_links", [])
            links_str = "\n".join([f"   • `{l}`" for l in links]) if links else "   • No activity."
                
            user_summaries.append(
                f"👤 *Name:* {info.get('first_name')} (ID: `{uid}`)\n"
                f"🔗 *Username:* {info.get('username')}\n"
                f"📥 *Downloads:* `{info.get('downloads_count')}` | 💬 *Msgs:* `{info.get('msg_count')}`\n"
                f"📌 *All Activity & Links:*\n{links_str}\n"
                f"----------------------------------------"
            )
        
        users_text = "\n\n".join(user_summaries) if user_summaries else "No user records found."
        
        if len(users_text) > 3800:
            chunks = [users_text[i:i+3800] for i in range(0, len(users_text), 3800)]
            target_bot.reply_to(message, f"📊 *Admin Statistics*\n👥 Total Users: `{total_users}`\n📥 Total Downloads: `{total_downloads}`", parse_mode="Markdown")
            for chunk in chunks:
                target_bot.send_message(ADMIN_ID, chunk, parse_mode="Markdown")
        else:
            stats_text = (
                f"📊 *Admin Dashboard Statistics*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 *Total Users:* `{total_users}`\n"
                f"📥 *Total Downloads:* `{total_downloads}`\n\n"
                f"📋 *All Users History:*\n\n{users_text}\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            target_bot.reply_to(message, stats_text, parse_mode="Markdown")

    @target_bot.message_handler(commands=['userinfo'])
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
                    f"👤 *User History*\n"
                    f"📛 Name: {info.get('first_name')}\n"
                    f"🔗 Username: {info.get('username')}\n"
                    f"🆔 ID: `{target_id}`\n"
                    f"💬 Messages: `{info.get('msg_count')}`\n"
                    f"📥 Total Downloads: `{info.get('downloads_count')}`\n\n"
                    f"🔗 *All Messages/Links:*\n{links_str}"
                )
                target_bot.reply_to(message, info_text, parse_mode="Markdown")
            else:
                target_bot.reply_to(message, "❌ *User ID not found.*", parse_mode="Markdown")
        except Exception:
            target_bot.reply_to(message, "⚠️ *Usage:* `/userinfo <user_id>`", parse_mode="Markdown")

    @target_bot.message_handler(commands=['maintenance'])
    def toggle_maintenance(message):
        if message.chat.id != ADMIN_ID:
            return
        config = get_config()
        current = config.get("maintenance", False)
        config["maintenance"] = not current
        save_data(CONFIG_FILE, config)
        
        status = "ON 🛠️ (Bot locked)" if config["maintenance"] else "OFF ✅ (Bot live)"
        target_bot.reply_to(message, f"🛠️ *Maintenance Mode is now {status}*", parse_mode="Markdown")

        if config["maintenance"]:
            users_db = load_data(USER_FILE)
            for uid in users_db.keys():
                try:
                    target_bot.send_message(
                        uid, 
                        "⚠️ *Notice:* The bot is currently undergoing maintenance and will be temporarily unavailable. We will be back online soon!", 
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

    @target_bot.message_handler(commands=['broadcast'])
    def broadcast_message(message):
        if message.chat.id != ADMIN_ID:
            return
        msg_to_send = message.text.replace("/broadcast", "").strip()
        if not msg_to_send:
            target_bot.reply_to(message, "⚠️ *Usage:* `/broadcast Your message here`", parse_mode="Markdown")
            return
        users_db = load_data(USER_FILE)
        sent, failed = 0, 0
        for uid in users_db.keys():
            try:
                target_bot.send_message(uid, f"📢 *Announcement:*\n\n{msg_to_send}", parse_mode="Markdown")
                sent += 1
            except Exception:
                failed += 1
        target_bot.reply_to(message, f"✅ Broadcast Finished!\n🟢 Sent: `{sent}` | 🔴 Failed: `{failed}`", parse_mode="Markdown")

    @target_bot.message_handler(func=lambda message: True)
    def process_message(message):
        if is_banned(message.chat.id):
            target_bot.reply_to(message, "❌ *You are banned from using this bot!*", parse_mode="Markdown")
            return

        config = get_config()
        if config.get("maintenance", False) and message.chat.id != ADMIN_ID:
            target_bot.reply_to(message, "🛠️ *Bot is under maintenance! Please try again later.*", parse_mode="Markdown")
            return

        text = message.text.strip()
        chat_id = message.chat.id

        track_user_activity(message.from_user, "User Message Sent", text)

        if text == "📊 My Stats":
            user_stats(message)
            return
        elif text == "🔗 Referral Link":
            bot_username = target_bot.get_me().username
            ref_link = f"https://t.me/{bot_username}?start={chat_id}"
            target_bot.reply_to(message, f"👥 *Your Referral Link:*\n`{ref_link}`", parse_mode="Markdown")
            return
        elif text == "🤖 AI Chat":
            AI_ACTIVE_CHATS.add(chat_id)
            target_bot.reply_to(message, "🤖 *Meta AI Chat Mode Activated!*\n\nNow type anything to chat with AI. Send /start to exit.", parse_mode="Markdown")
            return
        elif text == "🚀 Create Own Bot":
            target_bot.reply_to(message, "🤖 *Send your Bot Token now!*\n\nJust paste your Telegram Bot Token here and I will instantly make your bot LIVE!", parse_mode="Markdown")
            return

        # Bot Token Auto Detection Check
        if re.match(r'^\d{8,11}:[A-Za-z0-9_-]{35,}$', text):
            status_msg = target_bot.reply_to(message, "⚡ *Connecting & Deploying Your Bot Token...*", parse_mode="Markdown")
            success, msg = deploy_cloned_bot(text, chat_id)
            target_bot.edit_message_text(msg, chat_id, status_msg.message_id, parse_mode="Markdown")
            return

        # Instagram Download Handling
        if "instagram.com" in text.lower():
            status_msg = target_bot.reply_to(message, "⏳ *Downloading Instagram media...* 🚀", parse_mode="Markdown")
            video_url = download_instagram(text)
            if video_url:
                try:
                    target_bot.send_video(chat_id, video_url, caption="📥 *Downloaded via Bot*", parse_mode="Markdown")
                    target_bot.delete_message(chat_id, status_msg.message_id)
                except Exception:
                    target_bot.edit_message_text("❌ *Video file is too large or failed to send.*", chat_id, status_msg.message_id, parse_mode="Markdown")
            else:
                target_bot.edit_message_text("❌ *Failed to fetch Instagram media. Try another link!*", chat_id, status_msg.message_id, parse_mode="Markdown")
            return

        # TikTok Download Handling
        elif "tiktok.com" in text.lower() or "vt.tiktok.com" in text.lower():
            status_msg = target_bot.reply_to(message, "⏳ *Downloading TikTok video...* 🎵", parse_mode="Markdown")
            video_url = download_tiktok(text)
            if video_url:
                try:
                    target_bot.send_video(chat_id, video_url, caption="📥 *Downloaded via Bot*", parse_mode="Markdown")
                    target_bot.delete_message(chat_id, status_msg.message_id)
                except Exception:
                    target_bot.edit_message_text("❌ *Video file is too large or failed to send.*", chat_id, status_msg.message_id, parse_mode="Markdown")
            else:
                target_bot.edit_message_text("❌ *Failed to fetch TikTok video. Try another link!*", chat_id, status_msg.message_id, parse_mode="Markdown")
            return

        # General Text / AI Conversation Handling
        status_msg = target_bot.reply_to(message, "🤖 *AI Assistant is typing...*", parse_mode="Markdown")
        ai_response = ask_meta_ai(text)
        try:
            target_bot.edit_message_text(ai_response, chat_id, status_msg.message_id, parse_mode="Markdown")
        except Exception:
            target_bot.send_message(chat_id, ai_response, parse_mode="Markdown")

# ----------------- MULTI-BOT AUTO-CLONE ENGINE ----------------- #
def deploy_cloned_bot(token: str, owner_id: int):
    token = token.strip()
    try:
        temp_bot = telebot.TeleBot(token)
        bot_info = temp_bot.get_me()
        bot_username = bot_info.username
        
        cloned_bots = load_data(CLONED_BOTS_FILE)
        if not isinstance(cloned_bots, dict):
            cloned_bots = {}
        
        cloned_bots[token] = {
            "owner_id": owner_id,
            "username": bot_username,
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_data(CLONED_BOTS_FILE, cloned_bots)
        
        if token not in RUNNING_CLONES:
            setup_bot_handlers(temp_bot, is_clone=True)
            t = threading.Thread(target=temp_bot.infinity_polling, daemon=True)
            t.start()
            RUNNING_CLONES[token] = t

        return True, f"🎉 *Success! Your Bot is now LIVE!*\n\n🤖 *Bot Username:* @{bot_username}\n✨ Anyone can now use @{bot_username} to download videos & talk with AI!"
    
    except Exception as e:
        LOG.error(f"Clone Deploy Error: {e}")
        return False, "❌ *Invalid Bot Token!* Please send a valid Telegram Bot Token from @BotFather."

def start_all_saved_clones():
    cloned_bots = load_data(CLONED_BOTS_FILE)
    if isinstance(cloned_bots, dict):
        for token in cloned_bots.keys():
            try:
                c_bot = telebot.TeleBot(token)
                setup_bot_handlers(c_bot, is_clone=True)
                t = threading.Thread(target=c_bot.infinity_polling, daemon=True)
                t.start()
                RUNNING_CLONES[token] = t
                LOG.info(f"Successfully started cloned bot: {token[:10]}...")
            except Exception as e:
                LOG.error(f"Failed to start saved clone {token[:10]}: {e}")

# ----------------- MAIN RUNNER ----------------- #
if __name__ == "__main__":
    setup_bot_handlers(main_bot, is_clone=False)
    
    start_all_saved_clones()
    
    threading.Thread(target=run_flask, daemon=True).start()
    LOG.info("Main bot & Clone engine started successfully...")
    main_bot.infinity_polling()
