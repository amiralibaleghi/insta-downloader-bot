import telebot
import os
# توکن رباتت که از BotFather گرفتی
TOKEN = os.getenv("TOKEN")

bot = telebot.TeleBot(TOKEN)

# وقتی کاربر هر پیامی فرستاد
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, f"پیامت رو گرفتم ✅\nمتنت: {message.text}")

print("ربات در حال اجراست...")
bot.infinity_polling()

