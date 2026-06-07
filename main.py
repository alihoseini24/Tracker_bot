import os
import logging
import asyncio
from threading import Thread
from http.server import SimpleHTTPRequestHandler, HTTPServer
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
from database import init_db, register_user, get_categories, add_custom_category, delete_category, rename_category, start_new_activity, get_report

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

def get_tracker_keyboard(user_id):
    categories = get_categories(user_id)
    keyboard = []
    for i in range(0, len(categories), 2):
        row = [KeyboardButton(categories[i])]
        if i + 1 < len(categories):
            row.append(KeyboardButton(categories[i+1]))
        keyboard.append(row)
    keyboard.append([KeyboardButton("⚙️ مدیریت دسته‌بندی‌ها")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    register_user(user_id, chat_id, user_name)
    try: await update.message.delete()
    except Exception: pass
    await context.bot.send_message(chat_id=chat_id, text=f"🎯 کاربر **{user_name}** ثبت شد. کیبورد اختصاصی شما فعال گردید.", reply_markup=get_tracker_keyboard(user_id))

async def manage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    try: await update.message.delete()
    except Exception: pass
    
    keyboard = [
        [InlineKeyboardButton("➕ افزودن دسته‌بندی", callback_data="mg_add")],
        [InlineKeyboardButton("❌ حذف دسته‌بندی", callback_data="mg_del")],
        [InlineKeyboardButton("✏️ تغییر نام دسته‌بندی", callback_data="mg_ren")]
    ]
    await context.bot.send_message(chat_id=chat_id, text=f"⚙️ **منوی مدیریت دسته‌بندی‌ها**\nیک گزینه را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    if data == "mg_add":
        context.user_data[f'action_{user_id}'] = 'adding'
        await query.message.edit_text("👤 لطفاً نام دسته‌بندی جدید را تایپ و ارسال کنید:")
        
    elif data == "mg_del":
        cats = get_categories(user_id)
        keyboard = [[InlineKeyboardButton(c, callback_data=f"del_{c}")] for c in cats]
        await query.message.edit_text("❌ کدام دسته‌بندی حذف شود؟", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "mg_ren":
        cats = get_categories(user_id)
        keyboard = [[InlineKeyboardButton(c, callback_data=f"renstart_{c}")] for c in cats]
        await query.message.edit_text("✏️ نام کدام دسته‌بندی را تغییر می‌دهید؟", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data.startswith("del_"):
        cat_to_del = data.replace("del_", "")
        delete_category(user_id, cat_to_del)
        await query.message.edit_text(f"✅ دسته‌بندی **{cat_to_del}** با موفقیت حذف شد.", reply_markup=None)
        # فرستادن کیبورد جدید بلافاصله بعد از حذف
        await context.bot.send_message(chat_id=query.message.chat_id, text="🔄 کیبورد شما به‌روزرسانی شد.", reply_markup=get_tracker_keyboard(user_id))
        
    elif data.startswith("renstart_"):
        cat_to_ren = data.replace("renstart_", "")
        context.user_data[f'action_{user_id}'] = 'renaming'
        context.user_data[f'old_name_{user_id}'] = cat_to_ren
        await query.message.edit_text(f"✏️ نام جدید را برای دسته‌بندی **{cat_to_ren}** ارسال کنید:")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    text = update.message.text.strip()
    
    if text == "⚙️ مدیریت دسته‌بندی‌ها" or text == "/manage":
        await manage_menu(update, context)
        return

    action = context.user_data.get(f'action_{user_id}')
    
    if action == 'adding':
        try: await update.message.delete()
        except Exception: pass
        add_custom_category(user_id, text)
        context.user_data[f'action_{user_id}'] = None
        await update.message.reply_text(f"✅ دسته‌بندی **{text}** برای **{user_name}** اضافه شد.", reply_markup=get_tracker_keyboard(user_id))
        return
        
    elif action == 'renaming':
        try: await update.message.delete()
        except Exception: pass
        old_name = context.user_data.get(f'old_name_{user_id}')
        rename_category(user_id, old_name, text)
        context.user_data[f'action_{user_id}'] = None
        context.user_data[f'old_name_{user_id}'] = None
        # اصلاح فیکس: فرستادن کیبورد جدید بلافاصله پس از تغییر نام
        await update.message.reply_text(f"✅ نام دسته‌بندی از **{old_name}** به **{text}** تغییر یافت.", reply_markup=get_tracker_keyboard(user_id))
        return

    # پردازش تسک‌ها
    user_categories = get_categories(user_id)
    if text in user_categories:
        try: await update.message.delete()
        except Exception: pass
            
        prev_info = start_new_activity(user_id, chat_id, text)
        msg = f"👤 **{user_name}** فعالیت جدید را شروع کرد: **{text}**"
        if prev_info:
            msg += f"\n⏱ فعالیت قبلی (**{prev_info['category']}**) به مدت **{prev_info['duration'] // 60} ساعت و {prev_info['duration'] % 60} دقیقه** طول کشید."
        await context.bot.send_message(chat_id=chat_id, text=msg)

async def send_daily_reports(context: ContextTypes.DEFAULT_TYPE):
    import sqlite3
    conn = sqlite3.connect("tracker.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, chat_id, user_name FROM users")
    users = cursor.fetchall()
    conn.close()
    
    for user_id, chat_id, user_name in users:
        report_msg = f"📊 **گزارش عملکرد شبانه {user_name}**\n\n📅 **امروز:**\n{get_report(user_id, 1)}\n📅 **این هفته:**\n{get_report(user_id, 7)}\n📅 **این ماه:**\n{get_report(user_id, 30)}"
        try: await context.bot.send_message(chat_id=chat_id, text=report_msg, parse_mode="Markdown")
        except Exception as e: logging.error(f"Error: {e}")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

def main():
    init_db()
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token: return

    Thread(target=run_health_check_server, daemon=True).start()
    application = Application.builder().token(token).build()
    
    from datetime import time
    import pytz
    application.job_queue.run_daily(send_daily_reports, time=time(hour=0, minute=0, second=0, tzinfo=pytz.timezone("Europe/Rome")))

    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("start", register))
    application.add_handler(CommandHandler("manage", manage_menu))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.run_polling()

if __name__ == '__main__':
    main()
