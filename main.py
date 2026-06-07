import os
import logging
import asyncio
from threading import Thread
from http.server import SimpleHTTPRequestHandler, HTTPServer
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
import sqlite3
from database import init_db, register_user, get_categories, add_custom_category, delete_category, rename_category, start_new_activity, cancel_active_activity, get_report

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

last_group_sync_msgs = {}

def get_tracker_keyboard(user_id):
    categories = get_categories(user_id)
    keyboard = []
    for i in range(0, len(categories), 2):
        row = [KeyboardButton(f"🔹 {categories[i]}")]
        if i + 1 < len(categories):
            row.append(KeyboardButton(f"🔹 {categories[i+1]}"))
        keyboard.append(row)
    keyboard.append([KeyboardButton("❌ Cancel Task"), KeyboardButton("⚙️ Manage")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_user_chat_id(user_id):
    conn = sqlite3.connect("tracker.db")
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

async def set_bot_commands(application: Application):
    commands = [
        BotCommand("register", "🎯 Register & active keyboard"),
        BotCommand("buttons", "🔄 Reload keyboard buttons"),
        BotCommand("manage", "⚙️ Manage categories")
    ]
    await application.bot.set_my_commands(commands)

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    register_user(user_id, chat_id, user_name)
    try: await update.message.delete()
    except Exception: pass
    await context.bot.send_message(chat_id=chat_id, text=f"🎯 Registered: {user_name}", reply_markup=get_tracker_keyboard(user_id))

async def refresh_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    try: await update.message.delete()
    except Exception: pass
    
    await context.bot.send_message(
        chat_id=chat_id, 
        text="🔄 Buttons reloaded", 
        reply_markup=get_tracker_keyboard(user_id)
    )

async def manage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    try: await update.message.delete()
    except Exception: pass
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Category", callback_data="mg_add")],
        [InlineKeyboardButton("🗑️ Delete Category", callback_data="mg_del")],
        [InlineKeyboardButton("✏️ Rename Category", callback_data="mg_ren")]
    ]
    await context.bot.send_message(chat_id=chat_id, text="⚙️ Manage Categories:", reply_markup=InlineKeyboardMarkup(keyboard))

async def sync_keyboards(context, user_id, current_chat_id, text_msg):
    global last_group_sync_msgs
    await context.bot.send_message(chat_id=current_chat_id, text=text_msg, reply_markup=get_tracker_keyboard(user_id))
    
    saved_chat_id = get_user_chat_id(user_id)
    if saved_chat_id and saved_chat_id != current_chat_id:
        if user_id in last_group_sync_msgs:
            try: await context.bot.delete_message(chat_id=saved_chat_id, message_id=last_group_sync_msgs[user_id])
            except Exception: pass
        try:
            msg = await context.bot.send_message(
                chat_id=saved_chat_id, 
                text=f"🔄 Keyboard updated: {context.user_data.get('user_name', 'User')}", 
                reply_markup=get_tracker_keyboard(user_id)
            )
            last_group_sync_msgs[user_id] = msg.message_id
        except Exception: pass

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data
    
    if data == "mg_add":
        context.user_data[f'action_{user_id}'] = 'adding'
        context.user_data[f'menu_msg_id_{user_id}'] = query.message.message_id
        await query.message.edit_text("➕ Type new category name:")
        
    elif data == "mg_del":
        cats = get_categories(user_id)
        keyboard = [[InlineKeyboardButton(c, callback_data=f"del_{c}")] for c in cats]
        await query.message.edit_text("🗑️ Select category to delete:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "mg_ren":
        cats = get_categories(user_id)
        keyboard = [[InlineKeyboardButton(c, callback_data=f"renstart_{c}")] for c in cats]
        await query.message.edit_text("✏️ Select category to rename:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data.startswith("del_"):
        cat_to_del = data.replace("del_", "")
        delete_category(user_id, cat_to_del)
        await query.message.edit_text(f"🗑️ Deleted: {cat_to_del}", reply_markup=None)
        await sync_keyboards(context, user_id, chat_id, "🔄 Keyboard updated")
        
    elif data.startswith("renstart_"):
        cat_to_ren = data.replace("renstart_", "")
        context.user_data[f'action_{user_id}'] = 'renaming'
        context.user_data[f'old_name_{user_id}'] = cat_to_ren
        context.user_data[f'menu_msg_id_{user_id}'] = query.message.message_id
        await query.message.edit_text(f"✏️ Type new name for {cat_to_ren}:")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    context.user_data['user_name'] = user_name
    text = update.message.text.strip()
    
    if text == "⚙️ Manage" or text == "/manage":
        await manage_menu(update, context)
        return

    if text == "❌ Cancel Task":
        try: await update.message.delete()
        except Exception: pass
        
        canceled_cat = cancel_active_activity(user_id)
        if canceled_cat:
            msg = f"❌ {user_name} canceled -> {canceled_cat}"
        else:
            msg = f"⚠️ {user_name} -> No active task"
            
        await context.bot.send_message(chat_id=chat_id, text=msg)
        return

    action = context.user_data.get(f'action_{user_id}')
    menu_msg_id = context.user_data.get(f'menu_msg_id_{user_id}')
    
    if action == 'adding':
        try: await update.message.delete()
        except Exception: pass
        add_custom_category(user_id, text)
        context.user_data[f'action_{user_id}'] = None
        
        if menu_msg_id:
            try: await context.bot.edit_message_text(chat_id=chat_id, message_id=menu_msg_id, text=f"➕ Added: {text}")
            except Exception: pass
        
        await sync_keyboards(context, user_id, chat_id, "🔄 Keyboard updated")
        return
        
    elif action == 'renaming':
        try: await update.message.delete()
        except Exception: pass
        old_name = context.user_data.get(f'old_name_{user_id}')
        rename_category(user_id, old_name, text)
        context.user_data[f'action_{user_id}'] = None
        context.user_data[f'old_name_{user_id}'] = None
        
        if menu_msg_id:
            try: await context.bot.edit_message_text(chat_id=chat_id, message_id=menu_msg_id, text=f"✏️ Renamed: {old_name} -> {text}")
            except Exception: pass
            
        await sync_keyboards(context, user_id, chat_id, "🔄 Keyboard updated")
        return

    # --- بخش اصلاح‌شده که دنبالش بودی اینجاست ---
    clean_text = text.replace("🔹 ", "").strip()
    user_categories = get_categories(user_id)
    
    if clean_text in user_categories:
        try: await update.message.delete()
        except Exception: pass
            
        prev_info = start_new_activity(user_id, chat_id, clean_text)
        
        if prev_info:
            prev_msg = f"⏱️ {user_name} finished {prev_info['category']}: {prev_info['duration'] // 60}h {prev_info['duration'] % 60}m"
            await context.bot.send_message(chat_id=chat_id, text=prev_msg)
            
        new_msg = f"👤 {user_name} ➔ {clean_text}"
        await context.bot.send_message(chat_id=chat_id, text=new_msg)
        return

async def send_daily_reports(context: ContextTypes.DEFAULT_TYPE):
    import sqlite3
    conn = sqlite3.connect("tracker.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, chat_id, user_name FROM users")
    users = cursor.fetchall()
    conn.close()
    
    for user_id, chat_id, user_name in users:
        report_msg = f"📊 Report: {user_name}\n\n📅 Today:\n{get_report(user_id, 1)}\n📅 Week:\n{get_report(user_id, 7)}\n📅 Month:\n{get_report(user_id, 30)}"
        try: await context.bot.send_message(chat_id=chat_id, text=report_msg)
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
    
    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.ensure_future(set_bot_commands(application))
    else:
        loop.run_until_complete(set_bot_commands(application))
    
    from datetime import time
    import pytz
    application.job_queue.run_daily(send_daily_reports, time=time(hour=0, minute=0, second=0, tzinfo=pytz.timezone("Europe/Rome")))

    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("start", register))
    application.add_handler(CommandHandler("buttons", refresh_buttons))
    application.add_handler(CommandHandler("manage", manage_menu))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.run_polling()

if __name__ == '__main__':
    main()
