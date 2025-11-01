# bot.py
import os
import re
import time
import tempfile
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import telebot
from telebot import types
import requests

# ---------- تنظیمات ----------
COOLDOWN_SECONDS = 30
MAX_SEND_SIZE = 50 * 1024 * 1024  # 50 MB
YT_DLP_TIMEOUT = 300
WORKERS = 2
CHANNEL_USERNAME = "@viraa_land"
# -----------------------------

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN environment variable is not set")

bot = telebot.TeleBot(TOKEN)
executor = ThreadPoolExecutor(max_workers=WORKERS)

# الگوهای دقیق لینک
INSTAGRAM_REGEX = re.compile(r"https?://(www\.)?instagram\.com/[^\s]+")
YOUTUBE_REGEX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/[^\s]+")
SOUNDCLOUD_REGEX = r"(https?://(on\.soundcloud\.com|soundcloud\.com)/[^\s]+)"

# دیکشنری‌ها
last_request_time = {}
user_platform = {}
daily_downloads = {}  # user_id -> { "instagram": {...}, "youtube": {...}, "soundcloud": {...} }

# محدودیت‌های روزانه برای هر پلتفرم
LIMITS_PER_PLATFORM = {
    "instagram": 4,
    "youtube": 1,
    "soundcloud": 10
}

def is_user_joined(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception:
        return False

def user_allowed(user_id):
    now = time.time()
    last = last_request_time.get(user_id, 0)
    if now - last < COOLDOWN_SECONDS:
        return False, int(COOLDOWN_SECONDS - (now - last))
    last_request_time[user_id] = now
    return True, 0

def check_daily_limit(user_id, platform):
    now = time.time()
    user_data = daily_downloads.get(user_id, {})
    platform_data = user_data.get(platform, {"count": 0, "last_reset": now})

    # ریست روزانه
    if now - platform_data["last_reset"] > 24 * 60 * 60:
        platform_data = {"count": 0, "last_reset": now}

    max_limit = LIMITS_PER_PLATFORM.get(platform, 3)
    if platform_data["count"] >= max_limit:
        return False, 0, max_limit

    platform_data["count"] += 1
    user_data[platform] = platform_data
    daily_downloads[user_id] = user_data
    return True, max_limit - platform_data["count"], max_limit

def run_yt_dlp_download(url, outdir):
    out_template = str(Path(outdir) / "%(id)s.%(ext)s")
    cmd = ["yt-dlp", "-o", out_template, url]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=YT_DLP_TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {proc.stderr.strip()[:1000]}")
    files = sorted(Path(outdir).iterdir(), key=lambda p: p.stat().st_mtime)
    return [str(p) for p in files]

def get_direct_urls(url):
    cmd = ["yt-dlp", "--get-url", url]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp --get-url failed: {proc.stderr.strip()}")
    urls = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return urls

def send_platform_menu(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Instagram", "Youtube", "Soundcloud")
    bot.send_message(chat_id, "پلتفرم مورد نظرت رو انتخاب کن 👇", reply_markup=markup)

@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    if not is_user_joined(user_id):
        markup = types.InlineKeyboardMarkup()
        join_button = types.InlineKeyboardButton("عضویت در کانال ViraLand", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")
        refresh_button = types.InlineKeyboardButton("✅ بررسی دوباره عضویت", callback_data="check_join")
        markup.add(join_button)
        markup.add(refresh_button)
        bot.reply_to(message, "برای استفاده از ربات باید در کانال عضو شوی 😍\nبعد از عضویت روی بررسی دوباره بزن 👇", reply_markup=markup)
        return
    send_platform_menu(message.chat.id)

def process_download(chat_id, user_id, url, platform):
    try:
        bot.send_message(chat_id, f"⏳ در حال دانلود از {platform} ... لطفاً صبر کنید.")
        with tempfile.TemporaryDirectory() as tmpdir:
            files = run_yt_dlp_download(url, tmpdir)
            if not files:
                bot.send_message(chat_id, "فایلی پیدا نشد یا نتوانستم دانلود کنم ❌")
                return
            for fpath in files:
                fsize = os.path.getsize(fpath)
                fname = os.path.basename(fpath)
                if fsize <= MAX_SEND_SIZE:
                    bot.send_document(chat_id, open(fpath, "rb"))
                    time.sleep(1)
                else:
                    urls = get_direct_urls(url)
                    bot.send_message(chat_id, "فایل بزرگتر از حد مجاز (50MB) است. لینک مستقیم 👇")
                    for u in urls:
                        bot.send_message(chat_id, u)
                        time.sleep(1)
    except Exception as e:
        bot.send_message(chat_id, f"خطا در دانلود از {platform}: {e}")

@bot.message_handler(func=lambda m: True)
def handle_all(message):
    text = (message.text or "").strip()
    chat_id = message.chat.id
    user_id = message.from_user.id

    # انتخاب پلتفرم
    if text == "Instagram":
        bot.reply_to(message, "لینک پست اینستاگرام را بفرست ✨")
        user_platform[user_id] = "instagram"
        return
    elif text == "Youtube":
        bot.reply_to(message, "لینک ویدیوی یوتیوب را بفرست 🎥")
        user_platform[user_id] = "youtube"
        return
    elif text == "Soundcloud":
        bot.reply_to(message, "لینک ترک یا پلی‌لیست ساندکلاد را بفرست 🎶")
        user_platform[user_id] = "soundcloud"
        return

    # بررسی عضویت
    if not is_user_joined(user_id):
        markup = types.InlineKeyboardMarkup()
        join_button = types.InlineKeyboardButton("عضویت در کانال ViraLand", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")
        refresh_button = types.InlineKeyboardButton("✅ بررسی دوباره عضویت", callback_data="check_join")
        markup.add(join_button)
        markup.add(refresh_button)
        bot.reply_to(message, "برای استفاده از ربات باید عضو کانال شوی 😍", reply_markup=markup)
        return

    # چک cooldown
    ok, wait = user_allowed(user_id)
    if not ok:
        bot.reply_to(message, f"کمی صبر کن لطفاً — {wait} ثانیه دیگه امتحان کن.")
        return

    platform = user_platform.get(user_id)
    if not platform:
        bot.reply_to(message, "ابتدا یکی از پلتفرم‌ها را از منوی اصلی انتخاب کن 👆")
        return

    # بررسی لینک بر اساس پلتفرم
    valid = False
    if platform == "instagram" and INSTAGRAM_REGEX.search(text):
        valid = True
    elif platform == "youtube" and YOUTUBE_REGEX.search(text):
        valid = True
    elif platform == "soundcloud" and SOUNDCLOUD_REGEX.search(text):
        valid = True

    if not valid:
        bot.reply_to(message, f"❌ لینک معتبر {platform} ارسال نشده است.")
        return

    # محدودیت روزانه بر اساس پلتفرم
    ok_daily, remain, max_limit = check_daily_limit(user_id, platform)
    if not ok_daily:
        bot.reply_to(message, f"🚫 به حد مجاز {max_limit} دانلود روزانه از {platform} رسیدی.\nفردا دوباره امتحان کن.")
        return

    url = text
    executor.submit(process_download, chat_id, user_id, url, platform)
    bot.reply_to(message, f"✅ درخواستت ثبت شد — در حال دانلود از {platform}...")

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    user_id = call.from_user.id
    if is_user_joined(user_id):
        bot.answer_callback_query(call.id, "✅ عضویت تایید شد!")
        send_platform_menu(call.message.chat.id)
    else:
        bot.answer_callback_query(call.id, "❌ هنوز عضو کانال نشدی!")

if __name__ == "__main__":
    print("Bot started (polling)...")
    bot.infinity_polling()
