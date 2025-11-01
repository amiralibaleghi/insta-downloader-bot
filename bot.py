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

# ---------- تنظیمات ----------
COOLDOWN_SECONDS = 30          # فاصله زمانی بین درخواست‌های یک کاربر
MAX_SEND_SIZE = 50 * 1024 * 1024  # 50 MB
YT_DLP_TIMEOUT = 300           # ثانیه (حداکثر زمان دانلود)
WORKERS = 2                    # تعداد thread برای پردازش هم‌زمان دانلودها
# -----------------------------
CHANNEL_USERNAME = "@viraa_land"

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN environment variable is not set")

bot = telebot.TeleBot(TOKEN)
executor = ThreadPoolExecutor(max_workers=WORKERS)

INSTAGRAM_REGEX = re.compile(r"https?://(www\.)?instagram\.com/[^\s]+")
YOUTUBE_REGEX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/[^\s]+")
SOUNDCLOUD_REGEX = re.compile(r"https?://(www\.)?soundcloud\.com/[^\s]+")

# جدا کردن دیکشنری‌ها تا تداخل نداشته باشیم
last_request_time = {}  # user_id -> timestamp (برای cooldown)
user_platform = {}      # user_id -> "instagram" | "youtube" | "soundcloud"

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

def run_yt_dlp_download(url, outdir):
    """
    دانلود پست با yt-dlp به outdir
    برمی‌گرداند لیست مسیر فایل‌های دانلودشده
    """
    out_template = str(Path(outdir) / "%(id)s.%(ext)s")
    cmd = ["yt-dlp", "-o", out_template, url]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=YT_DLP_TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {proc.stderr.strip()[:1000]}")
    files = sorted(Path(outdir).iterdir(), key=lambda p: p.stat().st_mtime)
    return [str(p) for p in files]

def get_direct_urls(url):
    """در صورت بزرگ بودن فایل، آدرس/آدرس‌های دانلود مستقیم را می‌گیریم."""
    cmd = ["yt-dlp", "--get-url", url]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp --get-url failed: {proc.stderr.strip()}")
    urls = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return urls

def process_instagram_download(chat_id, user_id, url):
    try:
        bot.send_message(chat_id, "⏳ در حال آماده‌سازی دانلود... لطفاً صبر کنید.")
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                files = run_yt_dlp_download(url, tmpdir)
            except Exception as e:
                try:
                    urls = get_direct_urls(url)
                    if urls:
                        bot.send_message(chat_id, "دانلود مستقیم (قابل استفاده در مرورگر):")
                        for u in urls:
                            bot.send_message(chat_id, u)
                            time.sleep(1)
                    else:
                        bot.send_message(chat_id, f"خطا در دانلود: {e}")
                except Exception as e2:
                    bot.send_message(chat_id, f"خطا در دانلود و دریافت لینک مستقیم: {e2}")
                return

            if not files:
                bot.send_message(chat_id, "فایلی پیدا نشد یا نتوانستم دانلود کنم.")
                return

            for fpath in files:
                fsize = os.path.getsize(fpath)
                fname = os.path.basename(fpath)
                if fsize <= MAX_SEND_SIZE:
                    try:
                        bot.send_document(chat_id, open(fpath, "rb"))
                        time.sleep(1)
                    except Exception as e:
                        bot.send_message(chat_id, f"خطا در ارسال فایل {fname}: {e}")
                else:
                    try:
                        urls = get_direct_urls(url)
                        if urls:
                            bot.send_message(chat_id,
                                "فایل خیلی بزرگتر از حد مجاز ربات است. می‌تونی از این لینک‌ها دانلود کنی:")
                            for u in urls:
                                bot.send_message(chat_id, u)
                                time.sleep(1)
                        else:
                            bot.send_message(chat_id, "فایل بزرگه و نتونستم لینک مستقیمش رو بگیرم.")
                    except Exception as e:
                        bot.send_message(chat_id, f"خطا در گرفتن لینک مستقیم: {e}")
    except Exception as e:
        bot.send_message(chat_id, f"خطا رخ داد: {e}")

# منو ساز برای ارسال مجدد منوی انتخاب پلتفرم
def send_platform_menu(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("instagram", "Youtube", "Soundcloud")
    bot.send_message(chat_id, "پلتفرم مورد نظرت رو انتخاب کن 👇", reply_markup=markup)

@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    if not is_user_joined(user_id):
        markup = types.InlineKeyboardMarkup()
        join_button = types.InlineKeyboardButton(
            "عضویت در کانال ViraLand",
            url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"
        )
        refresh_button = types.InlineKeyboardButton("✅ بررسی دوباره عضویت", callback_data="check_join")
        markup.add(join_button)
        markup.add(refresh_button)
        bot.reply_to(message, "برای استفاده از ربات باید در کانال عضو شوی 😍\nبعد از عضویت روی بررسی دوباره بزن 👇", reply_markup=markup)
        return

    send_platform_menu(message.chat.id)

# global dict برای محدودیت روزانه
daily_downloads = {}  # user_id -> {"count": n, "last_reset": timestamp}
MAX_DOWNLOADS_PER_DAY = 4

def can_download(user_id):
    now = time.time()
    user_data = daily_downloads.get(user_id, {"count": 0, "last_reset": now})
    if now - user_data["last_reset"] > 24*60*60:
        user_data = {"count": 0, "last_reset": now}
    if user_data["count"] >= MAX_DOWNLOADS_PER_DAY:
        return False, 0
    user_data["count"] += 1
    daily_downloads[user_id] = user_data
    return True, MAX_DOWNLOADS_PER_DAY - user_data["count"]

@bot.message_handler(func=lambda m: True)
def handle_all(message):
    text = (message.text or "").strip()
    chat_id = message.chat.id
    user_id = message.from_user.id

    # انتخاب پلتفرم توسط کاربر
    if text == "📸 دانلود از اینستاگرام":
        bot.reply_to(message, "لینک پست اینستاگرام را بفرست ✨")
        user_platform[user_id] = "instagram"
        return
    elif text == "🎬 دانلود از یوتیوب":
        bot.reply_to(message, "لینک ویدیوی یوتیوب را بفرست 🎥")
        user_platform[user_id] = "youtube"
        return
    elif text == "🎵 دانلود از ساندکلاد":
        bot.reply_to(message, "لینک ترک یا پلی‌لیست ساندکلاد را بفرست 🎶")
        user_platform[user_id] = "soundcloud"
        return

    # بررسی عضویت در کانال
    if not is_user_joined(user_id):
        markup = types.InlineKeyboardMarkup()
        join_button = types.InlineKeyboardButton(
            "عضویت در کانال ViraLand",
            url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"
        )
        refresh_button = types.InlineKeyboardButton("✅ بررسی دوباره عضویت", callback_data="check_join")
        markup.add(join_button)
        markup.add(refresh_button)
        bot.reply_to(
            message,
            "برای استفاده از ربات باید در کانال ما عضو شوی 😍\nبعد از عضویت، روی دکمه بررسی دوباره بزن 👇",
            reply_markup=markup
        )
        return

    # چک cooldown
    ok, wait = user_allowed(user_id)
    if not ok:
        bot.reply_to(message, f"کمی صبر کن لطفاً — {wait} ثانیه دیگه امتحان کن.")
        return

    # بررسی محدودیت روزانه
    ok_daily, remaining = can_download(user_id)
    if not ok_daily:
        bot.reply_to(message, f"❌ امروز به حد اکثر {MAX_DOWNLOADS_PER_DAY} دانلود رسیدی.\nلطفاً فردا دوباره امتحان کن.")
        return

    # برداشتن پلتفرم انتخاب‌شده کاربر
    platform = user_platform.get(user_id)
    if not platform:
        bot.reply_to(message, "ابتدا یک پلتفرم از منو انتخاب کن 👆")
        return

    # بررسی لینک بر اساس پلتفرم
    if platform == "instagram":
        if not INSTAGRAM_REGEX.search(text):
            bot.reply_to(message, "لطفاً لینک یک پست اینستاگرام (مثلاً https://www.instagram.com/p/...) ارسال کن.")
            return
        url = INSTAGRAM_REGEX.search(text).group(0)
        executor.submit(process_instagram_download, chat_id, user_id, url)
        bot.reply_to(message, "درخواستت ثبت شد — در حال دانلود پست اینستاگرام... ⏳")
    elif platform == "youtube":
        if not YOUTUBE_REGEX.search(text):
            bot.reply_to(message, "لطفاً لینک ویدیوی یوتیوب معتبر بفرست 🎬")
            return
        url = YOUTUBE_REGEX.search(text).group(0)
        executor.submit(process_generic_download, chat_id, user_id, url, "یوتیوب")
        bot.reply_to(message, "درخواستت ثبت شد — در حال دانلود ویدیو از یوتیوب... ⏳")
    elif platform == "soundcloud":
        if not SOUNDCLOUD_REGEX.search(text):
            bot.reply_to(message, "لطفاً لینک ترک یا پلی‌لیست ساندکلاد معتبر بفرست 🎵")
            return
        url = SOUNDCLOUD_REGEX.search(text).group(0)
        executor.submit(process_generic_download, chat_id, user_id, url, "ساندکلاد")
        bot.reply_to(message, "درخواستت ثبت شد — در حال دانلود از ساندکلاد... ⏳")
    else:
        bot.reply_to(message, "پلتفرم نامشخص است. لطفاً از منوی اصلی یکی را انتخاب کن.")
        return

def process_generic_download(chat_id, user_id, url, platform_name):
    try:
        bot.send_message(chat_id, f"⏳ در حال دانلود از {platform_name} ... لطفاً صبر کنید.")
        with tempfile.TemporaryDirectory() as tmpdir:
            files = run_yt_dlp_download(url, tmpdir)
            if not files:
                bot.send_message(chat_id, "فایلی پیدا نشد یا دانلود نشد ❌")
                return
            for fpath in files:
                fsize = os.path.getsize(fpath)
                fname = os.path.basename(fpath)
                if fsize <= MAX_SEND_SIZE:
                    try:
                        bot.send_document(chat_id, open(fpath, "rb"))
                        time.sleep(1)
                    except Exception as e:
                        bot.send_message(chat_id, f"خطا در ارسال فایل {fname}: {e}")
                else:
                    urls = []
                    try:
                        urls = get_direct_urls(url)
                    except Exception as e:
                        bot.send_message(chat_id, f"خطا در گرفتن لینک مستقیم: {e}")
                    if urls:
                        bot.send_message(chat_id, "فایل بزرگ است. لینک مستقیم 👇")
                        for u in urls:
                            bot.send_message(chat_id, u)
                            time.sleep(1)
    except Exception as e:
        bot.send_message(chat_id, f"خطا در دانلود از {platform_name}: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    user_id = call.from_user.id
    if is_user_joined(user_id):
        bot.answer_callback_query(call.id, "✅ عضویت شما تایید شد!")
        # فرستادن منوی انتخاب پس از تایید عضویت
        send_platform_menu(call.message.chat.id)
    else:
        bot.answer_callback_query(call.id, "❌ هنوز عضو کانال نشدی!")

if __name__ == "__main__":
    print("Bot started (polling)...")
    bot.infinity_polling()
