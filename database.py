import sqlite3
from datetime import datetime, timedelta

DB_NAME = "tracker.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            category TEXT,
            start_time TEXT,
            end_time TEXT,
            duration_minutes INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            user_id INTEGER,
            category TEXT,
            PRIMARY KEY (user_id, category)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            user_name TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_groups (
            user_id INTEGER PRIMARY KEY,
            group_chat_id INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def register_user(user_id, chat_id, user_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users VALUES (?, ?, ?)', (user_id, chat_id, user_name))
    conn.commit()
    conn.close()

def register_group(user_id, group_chat_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO user_groups VALUES (?, ?)', (user_id, group_chat_id))
    conn.commit()
    conn.close()

def get_categories(user_id):
    default_cats = [
        "📚 Study", 
        "🍔 Meal", 
        "🍿 Snack", 
        "🛒 Grocery", 
        "🎬 Movie/Series", 
        "🚗 Commute", 
        "🏋️ Exercises", 
        "😴 Sleep"
    ]
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT category FROM categories WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows] if rows else default_cats

def add_custom_category(user_id, category):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT category FROM categories WHERE user_id = ?", (user_id,))
    if not cursor.fetchall():
        for cat in get_categories(user_id):
            cursor.execute("INSERT OR IGNORE INTO categories VALUES (?, ?)", (user_id, cat))
    cursor.execute("INSERT OR IGNORE INTO categories VALUES (?, ?)", (user_id, category.strip()))
    conn.commit()
    conn.close()

def delete_category(user_id, category):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT category FROM categories WHERE user_id = ?", (user_id,))
    if not cursor.fetchall():
        for cat in get_categories(user_id):
            cursor.execute("INSERT OR IGNORE INTO categories VALUES (?, ?)", (user_id, cat))
    
    cursor.execute("DELETE FROM categories WHERE user_id = ? AND category = ?", (user_id, category.strip()))
    conn.commit()
    conn.close()

def rename_category(user_id, old_name, new_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT category FROM categories WHERE user_id = ?", (user_id,))
    if not cursor.fetchall():
        for cat in get_categories(user_id):
            cursor.execute("INSERT OR IGNORE INTO categories VALUES (?, ?)", (user_id, cat))
            
    cursor.execute("UPDATE categories SET category = ? WHERE user_id = ? AND category = ?", (new_name.strip(), user_id, old_name.strip()))
    conn.commit()
    conn.close()

def start_new_activity(user_id, chat_id, category):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute('SELECT id, start_time FROM activities WHERE user_id = ? AND end_time IS NULL ORDER BY id DESC LIMIT 1', (user_id,))
    last_act = cursor.fetchone()
    
    prev_info = None
    if last_act:
        act_id, start_str = last_act
        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        duration = int((now - start_dt).total_seconds() / 60)
        cursor.execute('UPDATE activities SET end_time = ?, duration_minutes = ? WHERE id = ?', (now_str, duration, act_id))
        cursor.execute("SELECT category FROM activities WHERE id = ?", (act_id,))
        prev_info = {"category": cursor.fetchone()[0], "duration": duration}
    
    cursor.execute('INSERT INTO activities (user_id, chat_id, category, start_time) VALUES (?, ?, ?, ?)', (user_id, chat_id, category.strip(), now_str))
    conn.commit()
    conn.close()
    return prev_info

def cancel_active_activity(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT id, category FROM activities WHERE user_id = ? AND end_time IS NULL ORDER BY id DESC LIMIT 1', (user_id,))
    row = cursor.fetchone()
    
    if row:
        act_id, category = row
        cursor.execute('DELETE FROM activities WHERE id = ?', (act_id,))
        conn.commit()
        conn.close()
        return category
    conn.close()
    return None

def get_current_session(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT category, start_time FROM activities WHERE user_id = ? AND end_time IS NULL ORDER BY id DESC LIMIT 1', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        category, start_str = row
        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        duration = int((datetime.now() - start_dt).total_seconds() / 60)
        return {"category": category, "duration": duration}
    return None

def get_day_report_so_far(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # شروع از ابتدای امروز روز جاری
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    
    # محاسبات مربوط به کارهای بسته‌ شده‌ی امروز
    cursor.execute('''
        SELECT category, SUM(duration_minutes) 
        FROM activities 
        WHERE user_id = ? AND start_time >= ? AND duration_minutes IS NOT NULL 
        GROUP BY category
    ''', (user_id, today_start))
    rows = cursor.fetchall()
    
    totals = {cat: m for cat, m in rows}
    
    # اضافه کردن تسک باز جاری (اگر مال امروز باشد) به محاسبات گزارش
    cursor.execute('SELECT category, start_time FROM activities WHERE user_id = ? AND end_time IS NULL ORDER BY id DESC LIMIT 1', (user_id,))
    active = cursor.fetchone()
    if active:
        category, start_str = active
        if start_str >= today_start:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
            active_duration = int((datetime.now() - start_dt).total_seconds() / 60)
            totals[category] = totals.get(category, 0) + active_duration
            
    conn.close()
    return totals

def get_report(user_id, days):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('SELECT category, SUM(duration_minutes) FROM activities WHERE user_id = ? AND start_time >= ? AND duration_minutes IS NOT NULL GROUP BY category', (user_id, since_date))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows: return "None\n"
    return "".join([f"• {cat}: {m // 60}h {m % 60}m\n" for cat, m in rows])        "☕️ Snack", 
        "🛒 Grocery", 
        "🎬 Movie/Series/Anime", 
        "🚌 Commute", 
        "🏋️ Exercises", 
        "💤 Sleep"
    ]
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT category FROM categories WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows] if rows else default_cats

def add_custom_category(user_id, category):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT category FROM categories WHERE user_id = ?", (user_id,))
    if not cursor.fetchall():
        for cat in get_categories(user_id):
            cursor.execute("INSERT OR IGNORE INTO categories VALUES (?, ?)", (user_id, cat))
    cursor.execute("INSERT OR IGNORE INTO categories VALUES (?, ?)", (user_id, category.strip()))
    conn.commit()
    conn.close()

def delete_category(user_id, category):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT category FROM categories WHERE user_id = ?", (user_id,))
    if not cursor.fetchall():
        for cat in get_categories(user_id):
            cursor.execute("INSERT OR IGNORE INTO categories VALUES (?, ?)", (user_id, cat))
    
    cursor.execute("DELETE FROM categories WHERE user_id = ? AND category = ?", (user_id, category.strip()))
    conn.commit()
    conn.close()

def rename_category(user_id, old_name, new_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT category FROM categories WHERE user_id = ?", (user_id,))
    if not cursor.fetchall():
        for cat in get_categories(user_id):
            cursor.execute("INSERT OR IGNORE INTO categories VALUES (?, ?)", (user_id, cat))
            
    cursor.execute("UPDATE categories SET category = ? WHERE user_id = ? AND category = ?", (new_name.strip(), user_id, old_name.strip()))
    conn.commit()
    conn.close()

def start_new_activity(user_id, chat_id, category):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute('SELECT id, start_time FROM activities WHERE user_id = ? AND end_time IS NULL ORDER BY id DESC LIMIT 1', (user_id,))
    last_act = cursor.fetchone()
    
    prev_info = None
    if last_act:
        act_id, start_str = last_act
        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        duration = int((now - start_dt).total_seconds() / 60)
        cursor.execute('UPDATE activities SET end_time = ?, duration_minutes = ? WHERE id = ?', (now_str, duration, act_id))
        cursor.execute("SELECT category FROM activities WHERE id = ?", (act_id,))
        prev_info = {"category": cursor.fetchone()[0], "duration": duration}
    
    cursor.execute('INSERT INTO activities (user_id, chat_id, category, start_time) VALUES (?, ?, ?, ?)', (user_id, chat_id, category.strip(), now_str))
    conn.commit()
    conn.close()
    return prev_info

def cancel_active_activity(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT id, category FROM activities WHERE user_id = ? AND end_time IS NULL ORDER BY id DESC LIMIT 1', (user_id,))
    row = cursor.fetchone()
    
    if row:
        act_id, category = row
        cursor.execute('DELETE FROM activities WHERE id = ?', (act_id,))
        conn.commit()
        conn.close()
        return category
    conn.close()
    return None

def get_report(user_id, days):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('SELECT category, SUM(duration_minutes) FROM activities WHERE user_id = ? AND start_time >= ? AND duration_minutes IS NOT NULL GROUP BY category', (user_id, since_date))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows: return "None\n"
    return "".join([f"• {cat}: {m // 60}h {m % 60}m\n" for cat, m in rows])
