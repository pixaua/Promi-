from __future__ import annotations

import os
import threading
import requests
from datetime import datetime
import json
import re
from flask import Flask
import telebot
import yt_dlp

app = Flask(__name__)

@app.route('/')
def home():
    return "✨ 7G Main Bot is Online & Running!"

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ----------------- CONFIGURATION ----------------- #
BOT_TOKEN = "7678905793:AAGNMxC34F2dQ8bgojFAyGApeHA20Yk_8gI"  # Telegram Bot Token
ADMIN_ID = 6162953772                # Admin User ID

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
USER_FILE = os.path.join(DATA_DIR, "users_db.json")
BANNED_FILE = os.path.join(DATA_DIR, "banned_users.json")
CONFIG_FILE = os.path.join(DATA_DIR, "bot_config.json")
CLONED_BOTS_FILE = os.path.join(DATA_DIR, "cloned_bots.json")

main_bot = telebot.TeleBot(BOT_TOKEN)
RUNNING_CLONES = {}

# ----------------- DATABASE MANAGEMENT WITH TELEGRAM BACKUP ----------------- #
def load_data(filepath):
    if not os.path.exists(filepath):
        return {} if "users" in filepath or "config" in filepath else []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if "users" in filepath or "config" in filepath else []

def save_data(filepath, data, active_bot=None):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        
        if "users_db.json" in filepath:
            try:
                target_bot = active_bot if active_bot else main_bot
                with open(filepath, "rb") as bf:
                    target_bot.send_document(ADMIN_ID, bf, caption="🛡️ *Auto Telegram Database Backup Sync* ✨", parse_mode="Markdown")
            except Exception:
                pass
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

def track_user_activity(user, action_type, text_data="", referred_by=None, active_bot=None):
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
            "messages_list": [text_data] if "Message" in action_type and text_data else [],
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
        
        if "Message" in action_type and text_data:
            if "messages_list" not in users_db[user_id]:
                users_db[user_id]["messages_list"] = []
            users_db[user_id]["messages_list"].append(text_data)

    save_data(USER_FILE, users_db, active_bot)
    send_admin_alert(user, action_type, text_data, users_db[user_id], active_bot)

def send_admin_alert(user, action_type, text_data, user_info, active_bot=None):
    try:
        target_bot = active_bot if active_bot else main_bot
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
            f"📌 *Data/Link:* {text_data}\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        target_bot.send_message(ADMIN_ID, alert_msg, parse_mode="Markdown")
    except Exception as e:
        print(f"Admin Alert Error: {e}")

# ----------------- ADVANCED DOWNLOAD ENGINES ----------------- #
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

    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(f"https://tikwm.com/api/?url={url}", headers=headers, timeout=10).json()
        if "data" in res and "play" in res["data"]:
            return res["data"]["play"]
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

    ydl_opts = {'format': 'best', 'quiet': True, 'no_warnings': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'url' in info:
                return info['url']
    except Exception:
        pass
    return None

# ----------------- BOT HANDLERS SETUP ----------------- #
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

        track_user_activity(message.from_user, "Start Command / New Visitor", message.text, referred_by, target_bot)

        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        if not is_clone:
            markup.add(
                telebot.types.KeyboardButton("📊 My Stats"),
                telebot.types.KeyboardButton("🔗 Referral Link"),
                telebot.types.KeyboardButton("✨ Features Guide"),
                telebot.types.KeyboardButton("🚀 Create Own Bot")
            )
        else:
            markup.add(
                telebot.types.KeyboardButton("📊 My Stats"),
                telebot.types.KeyboardButton("🔗 Referral Link"),
                telebot.types.KeyboardButton("✨ Features Guide")
            )

        welcome_text = (
            "✨🔥 *Welcome to 7G Ultimate Bot!* 🔥✨\n\n"
            "📥 *Instagram & TikTok:* Send any link for instant HD download!\n\n"
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
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ *Thanks for using 7G Bot!* ❤️"
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
            msgs_list = info.get("messages_list", [])
            links_list = info.get("download_links", [])

            # সিরিয়াল নম্বর দিয়ে মেসেজ লিস্ট তৈরি (1, 2, 3...)
            if msgs_list:
                msgs_str = "\n".join([f"   {i+1}. `{m}`" for i, m in enumerate(msgs_list)])
            else:
                msgs_str = "   • No messages recorded."

            # সিরিয়াল নম্বর দিয়ে ডাউনলোড লিংক লিস্ট তৈরি (1, 2, 3...)
            if links_list:
                links_str = "\n".join([f"   {i+1}. `{l}`" for i, l in enumerate(links_list)])
            else:
                links_str = "   • No downloads yet."

            user_summaries.append(
                f"👤 *Name:* {info.get('first_name')} (ID: `{uid}`)\n"
                f"🔗 *Username:* {info.get('username')}\n"
                f"📥 *Downloads Count:* `{info.get('downloads_count')}` | 💬 *Messages Count:* `{info.get('msg_count')}`\n\n"
                f"💬 *Messages List:*\n{msgs_str}\n\n"
                f"📌 *Downloaded Links List:*\n{links_str}\n"
                f"----------------------------------------"
            )

        users_text = "\n\n".join(user_summaries) if user_summaries else "No user records found."

        if len(users_text) > 3800:
            chunks = [users_text[i:i+3800] for i in range(0, len(users_text), 3800)]
            target_bot.reply_to(message, f"📊 *Admin Dashboard Statistics*\n👥 Total Users: `{total_users}`\n📥 Total Downloads: `{total_downloads}`", parse_mode="Markdown")
            for chunk in chunks:
                target_bot.send_message(ADMIN_ID, chunk, parse_mode="Markdown")
        else:
            stats_text = (
                f"📊 *Admin Dashboard Statistics*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 *Total Users:* `{total_users}`\n"
                f"📥 *Total Downloads:* `{total_downloads}`\n\n"
                f"📋 *All Users Messages & Downloaded Links History:*\n\n{users_text}\n"
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
                msgs_list = info.get('messages_list', [])
                links_list = info.get('download_links', [])

                msgs_str = "\n".join([f"   {i+1}. `{m}`" for i, m in enumerate(msgs_list)]) if msgs_list else "   • No messages."
                links_str = "\n".join([f"   {i+1}. `{l}`" for i, l in enumerate(links_list)]) if links_list else "   • No downloads."

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
                    f"💬 *Messages List:*\n{msgs_str}\n\n"
                    f"🔗 *Downloaded Links List:*\n{links_str}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━"
                )
                target_bot.reply_to(message, info_text, parse_mode="Markdown")
            else:
                target_bot.reply_to(message, "❌ *User ID not found in database.*", parse_mode="Markdown")
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
        status = "ON 🛠️ (Bot is now locked for users)" if config["maintenance"] else "OFF ✅ (Bot is now running for everyone)"
        target_bot.reply_to(message, f"🛠️ *Maintenance Mode is now {status}*", parse_mode="Markdown")

        # মেইনটেন্যান্স অন করলে সবার কাছে ইংলিশে নোটিশ পাঠানো
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

    @target_bot.message_handler(commands=['ban'])
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
                target_bot.reply_to(message, f"✅ *User ID `{target_id}` has been successfully banned!*", parse_mode="Markdown")
            else:
                target_bot.reply_to(message, f"⚠️ *User ID `{target_id}` is already in the ban list.*", parse_mode="Markdown")
        except Exception:
            target_bot.reply_to(message, "⚠️ *Usage:* `/ban <user_id>`", parse_mode="Markdown")

    @target_bot.message_handler(commands=['unban'])
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
                target_bot.reply_to(message, f"✅ *User ID `{target_id}` has been unbanned!*", parse_mode="Markdown")
            else:
                target_bot.reply_to(message, f"⚠️ *User ID `{target_id}` was not banned.*", parse_mode="Markdown")
        except Exception:
            target_bot.reply_to(message, "⚠️ *Usage:* `/unban <user_id>`", parse_mode="Markdown")

    @target_bot.message_handler(commands=['broadcast'])
    def broadcast_message(message):
        if message.chat.id != ADMIN_ID:
            return

        msg_to_send = message.text.replace("/broadcast", "").strip()
        if not msg_to_send:
            target_bot.reply_to(message, "⚠️ *Usage:* `/broadcast Your message here`", parse_mode="Markdown")
            return

        users_db = load_data(USER_FILE)
        if not users_db:
            target_bot.reply_to(message, "❌ *No users found in database.*", parse_mode="Markdown")
            return

        sent = 0
        failed = 0
        for uid in users_db.keys():
            try:
                target_bot.send_message(uid, f"📢 *Admin Announcement:*\n\n{msg_to_send}", parse_mode="Markdown")
                sent += 1
            except Exception:
                failed += 1

        target_bot.reply_to(message, f"✅ *Broadcast Finished!*\n🟢 Sent: `{sent}`\n🔴 Failed: `{failed}`", parse_mode="Markdown")

    # ----------------- MESSAGE & LINK HANDLER ----------------- #
    @target_bot.message_handler(func=lambda message: True)
    def process_link(message):
        if is_banned(message.chat.id):
            target_bot.reply_to(message, "❌ *You are banned from using this bot!*", parse_mode="Markdown")
            return

        config = get_config()
        if config.get("maintenance", False) and message.chat.id != ADMIN_ID:
            target_bot.reply_to(message, "🛠️ *Bot is under maintenance! Please try again later.*", parse_mode="Markdown")
            return

        text = message.text.strip()

        if text == "📊 My Stats":
            user_stats(message)
            return
        elif text == "🔗 Referral Link":
            bot_username = target_bot.get_me().username
            ref_link = f"https://t.me/{bot_username}?start={message.chat.id}"
            target_bot.reply_to(message, f"👥 *Your Personal Referral Link:*\n`{ref_link}`\n\n_Share this link with your friends to invite them!_ ✨", parse_mode="Markdown")
            return
        elif text == "✨ Features Guide":
            help_text = (
                "📌 *7G Bot Features Guide:*\n"
                "1. **Instagram & TikTok:** Send any link to download videos instantly.\n"
                "2. **Menu Buttons:** Easily check your personal stats or get your invite link."
            )
            ta
