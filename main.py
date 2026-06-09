import os
import logging
import asyncio
import pytz
from datetime import time, datetime
from threading import Thread
from http.server import SimpleHTTPRequestHandler, HTTPServer
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
from database import (init_db, register_user, unregister_user, toggle_reminders, get_all_users_with_reminders,
                      register_group, get_categories, add_batch_categories, delete_category, rename_category, 
                      start_new_activity, cancel_active_activity, get_current_session, 
                      get_day_report_so_far, get_report, get_db_connection)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

last_group_sync_msgs = {}

def get_tracker_keyboard(user_id):
    categories = get_categories(user_id)
    keyboard = []
    for i in range(0, len(categories), 2):
        row = [KeyboardButton(categories[i])]
        if i + 1 < len(categories):
            row.append(KeyboardButton(categories[i+1]))
        keyboard.append(row)
    
    keyboard.append([KeyboardButton("⏱️ Current Session"), KeyboardButton("📊 Day Report")])
    keyboard.append([KeyboardButton("❌ Cancel Task"), KeyboardButton("⚙️ Manage")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_user_group_id(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT group_chat_id FROM user_groups WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row['group_chat_id'] if row else None
    except Exception:
        return None

async def set_bot_commands(application: Application):
    commands = [
        BotCommand("register", "🎯 Register & active keyboard"),
        BotCommand("buttons", "🔄 Reload keyboard buttons"),
        BotCommand("manage", "⚙️ Manage categories / options")
    ]
    try:
        await application.bot.set_my_commands(commands)
    except Exception as e:
        logging.error(f"Failed to set commands natively: {e}")

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    register_user(user_id, chat_id, user_name)
    if update.effective_chat.type in ["group", "supergroup"]:
        register_group(user_id, chat_id)
        
    try: await update.message.delete()
    except Exception: pass
    await context.bot.send_message(chat_id=chat_id, text=f"🎯 Registered: {user_name}", reply_markup=get_tracker_keyboard(user_id))

async def refresh_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    try: await update.message.delete()
    except Exception: pass
    
    await context.bot.send_message(chat_id=chat_id, text="🔄 Buttons reloaded", reply_markup=get_tracker_keyboard(user_id))

async def manage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    try: await update.message.delete()
    except Exception: pass
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Categories (Batch)", callback_data="mg_add_batch")],
        [InlineKeyboardButton("🗑️ Delete Category", callback_data="mg_del")],
        [InlineKeyboardButton("✏️ Rename Category", callback_data="mg_ren")],
        [InlineKeyboardButton("🔔 Toggle 15-Min Reminders", callback_data="mg_toggle_remind")],
        [InlineKeyboardButton("⚠️ Unregister from Bot", callback_data="mg_unreg_confirm")]
    ]
    await context.bot.send_message(chat_id=chat_id, text="⚙️ Manage System Options:", reply_markup=InlineKeyboardMarkup(keyboard))

async def sync_keyboards(context, user_id, current_chat_id, text_msg):
    global last_group_sync_msgs
    await context.bot.send_message(chat_id=current_chat_id, text=text_msg, reply_markup=get_tracker_keyboard(user_id))
    
    saved_group_id = get_user_group_id(user_id)
    if saved_group_id and saved_group_id != current_chat_id:
        if user_id in last_group_sync_msgs:
            try: await context.bot.delete_message(chat_id=saved_group_id, message_id=last_group_sync_msgs[user_id])
            except Exception: pass
        try:
            msg = await context.bot.send_message(
                chat_id=saved_group_id, 
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
    
    if data == "mg_add_batch":
        context.user_data[f'action_{user_id}'] = 'batch_adding'
        context.user_data[f'batch_list_{user_id}'] = []
        context.user_data[f'menu_msg_id_{user_id}'] = query.message.message_id
        await query.message.edit_text("➕ Type the FIRST new category name:")
        
    elif data == "batch_continue":
        context.user_data[f'action_{user_id}'] = 'batch_adding'
        await query.message.edit_text("➕ Type the NEXT category name:")
        
    elif data == "batch_finish":
        categories_to_add = context.user_data.get(f'batch_list_{user_id}', [])
        context.user_data[f'action_{user_id}'] = None
        
        if categories_to_add:
            add_batch_categories(user_id, categories_to_add)
            joined_cats = ", ".join(categories_to_add)
            await query.message.edit_text(f"✅ Batch processing complete! Added: {joined_cats}")
            await sync_keyboards(context, user_id, chat_id, "🔄 Keyboard updated with new categories")
        else:
            await query.message.edit_text("⚠️ No categories were added.")
        context.user_data[f'batch_list_{user_id}'] = []

    elif data == "mg_del":
        cats = get_categories(user_id)
        keyboard = [[InlineKeyboardButton(c, callback_data=f"del_{c}")] for c in cats]
        await query.message.edit_text("🗑️ Select category to delete:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data.startswith("del_"):
        cat_to_del = data.replace("del_", "")
        delete_category(user_id, cat_to_del)
        await query.message.edit_text(f"🗑️ Deleted: {cat_to_del}", reply_markup=None)
        await sync_keyboards(context, user_id, chat_id, "🔄 Keyboard updated")
        
    elif data == "mg_ren":
        cats = get_categories(user_id)
        keyboard = [[InlineKeyboardButton(c, callback_data=f"renstart_{c}")] for c in cats]
        await query.message.edit_text("✏️ Select category to rename:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data.startswith("renstart_"):
        cat_to_ren = data.replace("renstart_", "")
        context.user_data[f'action_{user_id}'] = 'renaming'
        context.user_data[f'old_name_{user_id}'] = cat_to_ren
        context.user_data[f'menu_msg_id_{user_id}'] = query.message.message_id
        await query.message.edit_text(f"✏️ Type new name for {cat_to_ren}:")

    elif data == "mg_toggle_remind":
        is_enabled = toggle_reminders(user_id)
        status_txt = "✅ Enabled" if is_enabled else "❌ Disabled"
        await query.message.edit_text(f"🔔 15-Minute Reminders are now: {status_txt}")

    elif data == "mg_unreg_confirm":
        keyboard = [
            [InlineKeyboardButton("🛑 Yes, Delete Me", callback_data="mg_unreg_final")],
            [InlineKeyboardButton("🔙 Cancel", callback_data="mg_cancel_unreg")]
        ]
        await query.message.edit_text("⚠️ Are you sure you want to unregister? This deletes your profile and clears you from reports.", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "mg_unreg_final":
        unregister_user(user_id)
        await query.message.edit_text("👋 You have been unregistered successfully. Bot keyboard removed.", reply_markup=None)
        await context.bot.send_message(chat_id=chat_id, text="Profile deleted.", reply_markup=ReplyKeyboardRemove())

    elif data == "mg_cancel_unreg":
        await query.message.edit_text("Operation canceled.")

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

    if text == "⏱️ Current Session":
        try: await update.message.delete()
        except Exception: pass
        
        current = get_current_session(user_id)
        if current:
            msg = f"⏱️ {user_name} active: {current['category']} ({current['duration'] // 60}h {current['duration'] % 60}m)"
        else:
            msg = f"⚠️ {user_name} -> No active task"
        await context.bot.send_message(chat_id=chat_id, text=msg)
        return

    if text == "📊 Day Report":
        try: await update.message.delete()
        except Exception: pass
        
        report_data = get_day_report_so_far(user_id)
        if report_data:
            lines = [f"• {cat}: {m // 60}h {m % 60}m" for cat, m in report_data.items()]
            msg = f"📊 Today so far ({user_name}):\n" + "\n".join(lines)
        else:
            msg = f"📊 Today so far ({user_name}):\nNone"
        await context.bot.send_message(chat_id=chat_id, text=msg)
        return

    action = context.user_data.get(f'action_{user_id}')
    menu_msg_id = context.user_data.get(f'menu_msg_id_{user_id}')
    
    if action == 'batch_adding':
        try: await update.message.delete()
        except Exception: pass
        
        if f'batch_list_{user_id}' not in context.user_data:
            context.user_data[f'batch_list_{user_id}'] = []
            
        context.user_data[f'batch_list_{user_id}'].append(text)
        context.user_data[f'action_{user_id}'] = None
        
        keyboard = [
            [InlineKeyboardButton("➕ Add Another One", callback_data="batch_continue")],
            [InlineKeyboardButton("✅ Save & Finish", callback_data="batch_finish")]
        ]
        current_list = "\n".join([f"- {c}" for c in context.user_data[f'batch_list_{user_id}']])
        follow_up_text = f"📝 Current items to add:\n{current_list}\n\nWhat would you like to do next?"
        if menu_msg_id:
            try: await context.bot.edit_message_text(chat_id=chat_id, message_id=menu_msg_id, text=follow_up_text, reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception: pass
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

    user_categories = get_categories(user_id)
    if text in user_categories:
        try: await update.message.delete()
        except Exception: pass
            
        prev_info = start_new_activity(user_id, chat_id, text)
        msg = f"👤 {user_name} ➔ {text}"
        if prev_info:
            msg += f"\n\n⏱️ Prev: {prev_info['category']} ({prev_info['duration'] // 60}h {prev_info['duration'] % 60}m)"
        await context.bot.send_message(chat_id=chat_id, text=msg)

async def check_focus_reminders(context: ContextTypes.DEFAULT_TYPE):
    tz = pytz.timezone("Europe/Rome")
    now_local = datetime.now(tz)
    
    # محدودیت زمانی از ساعت ۷ صبح تا ساعت ۲۳:۵۹ شب
    if now_local.hour < 7:
        return

    active_targets = get_all_users_with_reminders()
    for target in active_targets:
        u_id = target['user_id']
        pvt_chat_id = target['chat_id'] # ارسال فقط به چت خصوصی کاربر ثبت شده
        
        current = get_current_session(u_id)
        if current:
            reminder_msg = f"🔔 هنوز به {current['category']} مشغولی؟"
        else:
            reminder_msg = "🔔 به چه مشغولی؟ یه کار مفید انجام بده."
            
        try:
            await context.bot.send_message(chat_id=pvt_chat_id, text=reminder_msg)
        except Exception as e:
            logging.error(f"Could not send focus reminder to private chat {pvt_chat_id}: {e}")

async def send_daily_reports(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, chat_id, user_name FROM users")
        users = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        logging.error(f"Error fetching users for report: {e}")
        return
    
    for user in users:
        user_id, chat_id, user_name = user['user_id'], user['chat_id'], user['user_name']
        report_msg = f"📊 Report: {user_name}\n\n📅 Today:\n{get_report(user_id, 1)}\n📅 Week:\n{get_report(user_id, 7)}\n📅 Month:\n{get_report(user_id, 30)}"
        try: await context.bot.send_message(chat_id=chat_id, text=report_msg)
        except Exception as e: logging.error(f"Error sending report to {user_id}: {e}")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token or not os.environ.get("DATABASE_URL"):
        logging.error("Missing TELEGRAM_TOKEN or DATABASE_URL")
        return

    init_db()
    Thread(target=run_health_check_server, daemon=True).start()
    application = Application.builder().token(token).build()
    
    try:
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(set_bot_commands(application))
        except RuntimeError:
            asyncio.run(set_bot_commands(application))
    except Exception as e:
        logging.error(f"Failed to set bot commands due to timeout: {e}")
    
    tz_rome = pytz.timezone("Europe/Rome")
    
    # کرون جاب گزارش شبانه
    application.job_queue.run_daily(send_daily_reports, time=time(hour=0, minute=0, second=0, tzinfo=tz_rome))
    
    # کرون جاب یادآور تمرکز ۱۵ دقیقه‌ای (تکرار متوالی کل روز - فیلتر ساعت ۷ صبح داخل تابع اعمال می‌شود)
    application.job_queue.run_repeating(check_focus_reminders, interval=timedelta(minutes=15), first=time(hour=7, minute=0, second=0, tzinfo=tz_rome))

    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("start", register))
    application.add_handler(CommandHandler("buttons", refresh_buttons))
    application.add_handler(CommandHandler("manage", manage_menu))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.run_polling()

if __name__ == '__main__':
    main()
