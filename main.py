import os
import logging
import asyncio
from threading import Thread
from http.server import SimpleHTTPRequestHandler, HTTPServer
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from database import init_db, register_user, get_categories, add_custom_category, start_new_activity, get_report

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ساخت کیبورد پایین چت (به جای دکمه‌های شیشه‌ای زیر پیام)
def get_tracker_keyboard(user_id):
    categories = get_categories(user_id)
    keyboard = []
    
    # چیدن دکمه‌های تسک به صورت دو تایی
    for i in range(0, len(categories), 2):
        row = [KeyboardButton(categories[i])]
        if i + 1 < len(categories):
            row.append(KeyboardButton(categories[i+1]))
        keyboard.append(row)
    
    # اضافه کردن دکمه افزودن تسک جدید در انتها
    keyboard.append([KeyboardButton("➕ افزودن دسته‌بندی جدید")])
    
    # resize_keyboard=True باعث می‌شود دکمه‌ها کوچک و استاندارد شوند
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    register_user(user_id, chat_id, user_name)
    
    await update.message.reply_text(
        f"🎯 کاربر **{user_name}** ثبت شد. کیبورد اختصاصی شما در پایین چت فعال گردید.",
        reply_markup=get_tracker_keyboard(user_id)
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    text = update.message.text.strip()
    
    # ۱. بررسی وضعیت افزودن دسته‌بندی جدید
    if context.user_data.get(f'waiting_{user_id}'):
        add_custom_category(user_id, text)
        context.user_data[f'waiting_{user_id}'] = False
        await update.message.reply_text(
            f"✅ دسته‌بندی **{text}** برای **{user_name}** اضافه شد.",
            reply_markup=get_tracker_keyboard(user_id)
        )
        return

    # ۲. اگر دکمه "افزودن دسته‌بندی جدید" فشرده شد
    if text == "➕ افزودن دسته‌بندی جدید":
        context.user_data[f'waiting_{user_id}'] = True
        await update.message.reply_text(f"👤 **{user_name}**، نام دسته‌بندی جدید را تایپ و ارسال کنید:")
        return

    # ۳. پردازش دکمه‌های تسک‌ها
    categories = get_categories(user_id)
    if text in categories:
        prev_info = start_new_activity(user_id, chat_id, text)
        msg = f"👤 **{user_name}** فعالیت جدید را شروع کرد: **{text}**"
        if prev_info:
            msg += f"\n⏱ فعالیت قبلی (**{prev_info['category']}**) به مدت **{prev_info['duration'] // 60} ساعت و {prev_info['duration'] % 60} دقیقه** طول کشید."
        await update.message.reply_text(msg)

async def send_daily_reports(context: ContextTypes.DEFAULT_TYPE):
    import sqlite3
    conn = sqlite3.connect("tracker.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, chat_id, user_name FROM users")
    users = cursor.fetchall()
    conn.close()
    
    for user_id, chat_id, user_name in users:
        report_msg = (
            f"📊 **گزارش عملکرد شبانه {user_name}**\n\n"
            f"📅 **امروز:**\n{get_report(user_id, 1)}\n"
            f"📅 **این هفته:**\n{get_report(user_id, 7)}\n"
            f"📅 **این ماه:**\n{get_report(user_id, 30)}"
        )
        try:
            await context.bot.send_message(chat_id=chat_id, text=report_msg, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Error sending report: {e}")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

def main():
    init_db()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        return

    Thread(target=run_health_check_server, daemon=True).start()

    application = Application.builder().token(token).build()
    
    from datetime import time
    import pytz
    application.job_queue.run_daily(send_daily_reports, time=time(hour=0, minute=0, second=0, tzinfo=pytz.timezone("Europe/Rome")))

    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("start", register))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.run_polling()

if __name__ == '__main__':
    main()
