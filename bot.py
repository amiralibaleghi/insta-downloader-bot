# bot.py
import os
import re
import time
import tempfile
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import telebot

# ---------- تنظیمات ----------
COOLDOWN_SECONDS = 30          # فاصله زمانی بین درخواست‌های یک کاربر
MAX_SEND_SIZE = 50 * 1024 * 1024  # 50 MB
YT_DLP_TIMEOUT = 300           # ثانیه (حداکثر زمان دانلود)
WORKERS = 2                    # تعداد thread برای پردازش هم‌زمان دانلودها
# -----------------------------

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN environment variable is not set")

bot = telebot.TeleBot(TOKEN)
executor = ThreadPoolExecutor(max_workers=WORKERS)

INSTAGRAM_REGEX = re.compile(r"https?://(www\.)?instagram\.com/[^\s]+")

# ساده‌ترین نقشه برای cooldown
last_request = {}  # user_id -> timestamp

def user_allowed(user_id):
    now = time.time()
    last = last_request.get(user_id, 0)
    if now - last < COOLDOWN_SECONDS:
        return False, int(COOLDOWN_SECONDS - (now - last))
    last_request[user_id] = now
    return True, 0

def run_yt_dlp_download(url, outdir):
    """
    دانلود پست با yt-dlp به outdir
    برمی‌گرداند لیست مسیر فایل‌های دانلودشده
    """
    out_template = str(Path(outdir) / "%(id)s.%(ext)s")
    cmd = ["yt-dlp", "-o", out_template, url]
    # --no-playlist to avoid downloading entire profile if link is ambiguous
    # but for posts, usually fine. اضافه‌ش کن اگر لازم شد:
    # cmd.insert(1, "--no-playlist")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=YT_DLP_TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {proc.stderr.strip()[:1000]}")
    # فایل‌های خروجی
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
        bot.send_message(chat_id, "⏳ در حال آماده‌سازی دانلود... لطفاً صبر کن.")
        # پوشه موقت
        with tempfile.TemporaryDirectory() as tmpdir:
            # دانلود با yt-dlp
            try:
                files = run_yt_dlp_download(url, tmpdir)
            except Exception as e:
                # اگر دانلود شکست خورد سعی کن آدرس مستقیم بدهیم (احتمالاً برای فایل بزرگ)
                try:
                    urls = get_direct_urls(url)
                    if urls:
                        bot.send_message(chat_id, "دانلود مستقیم (قابل استفاده در مرورگر):")
                        for u in urls:
                            bot.send_message(chat_id, u)
                    else:
                        bot.send_message(chat_id, f"خطا در دانلود: {e}")
                except Exception as e2:
                    bot.send_message(chat_id, f"خطا در دانلود و دریافت لینک مستقیم: {e2}")
                return

            if not files:
                bot.send_message(chat_id, "فایلی پیدا نشد یا نتوانستم دانلود کنم.")
                return

            # برای هر فایل تصمیم می‌گیریم ارسال کنیم یا لینک مستقیم بدیم
            for fpath in files:
                fsize = os.path.getsize(fpath)
                fname = os.path.basename(fpath)
                if fsize <= MAX_SEND_SIZE:
                    # ارسال مستقیم
                    try:
                        # اگر لازم شد تشخیص نوع محتوا (تصویر/ویدیو) اضافه کن
                        bot.send_document(chat_id, open(fpath, "rb"))
                    except Exception as e:
                        bot.send_message(chat_id, f"خطا در ارسال فایل {fname}: {e}")
                else:
                    # فایل خیلی بزرگه -> ارسال لینک مستقیم
                    try:
                        urls = get_direct_urls(url)
                        if urls:
                            bot.send_message(chat_id,
                                "فایل خیلی بزرگتر از حد مجاز ربات است. می‌تونی از این لینک‌ها دانلود کنی:")
                            for u in urls:
                                bot.send_message(chat_id, u)
                        else:
                            bot.send_message(chat_id, "فایل بزرگه و نتونستم لینک مستقیمش رو بگیرم.")
                    except Exception as e:
                        bot.send_message(chat_id, f"خطا در گرفتن لینک مستقیم: {e}")

            # tmpdir با خروج از بلوک پاک می‌شود
    except Exception as e:
        bot.send_message(chat_id, f"خطا رخ داد: {e}")


@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.reply_to(message, "سلام! لینک پست اینستاگرام را بفرست تا تلاش کنم دانلودش کنم.\nتوجه: فقط پست‌های عمومی پشتیبانی می‌شوند.")

@bot.message_handler(func=lambda m: True)
def handle_all(message):
    text = (message.text or "").strip()
    chat_id = message.chat.id
    user_id = message.from_user.id

    # چک cooldown
    ok, wait = user_allowed(user_id)
    if not ok:
        bot.reply_to(message, f"کمی صبر کن لطفاً — {wait} ثانیه دیگه امتحان کن.")
        return

    # آیا لینک اینستاگرام است؟
    m = INSTAGRAM_REGEX.search(text)
    if not m:
        bot.reply_to(message, "لطفاً لینک یک پست اینستاگرام (مثلاً https://www.instagram.com/p/...) ارسال کن.")
        return

    url = m.group(0)
    # اجرا در thread جداگانه تا bot responsive بمونه
    executor.submit(process_instagram_download, chat_id, user_id, url)
    bot.reply_to(message, "درخواستت ثبت شد — دانلود در حال انجام است. پیام موفق/خطا را همین‌جا دریافت می‌کنی.")

if __name__ == "__main__":
    print("Bot started (polling)...")
    bot.infinity_polling()


