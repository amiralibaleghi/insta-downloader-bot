import telebot
import os

TOKEN = os.getenv("TOKEN")

bot = telebot.TeleBot(TOKEN)


@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, f"پیامت رو گرفتم ✅\nمتنت: {message.text}")

print("ربات در حال اجراست...")
bot.infinity_polling()

