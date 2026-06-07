import os
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, timedelta

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)

def init_db():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activities (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                chat_id BIGINT,
                category TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                duration_minutes INTEGER
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                user_id BIGINT,
                category TEXT,
                PRIMARY KEY (user_id, category)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                chat_id BIGINT,
                user_name TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_groups (
                user_id BIGINT PRIMARY KEY,
                group_chat_id BIGINT
            )
        ''')
        conn.commit()
        cursor.close()
    finally:
        conn.close()

def register_user(user_id, chat_id, user_name):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (user_id, chat_id, user_name) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (user_id) DO UPDATE SET chat_id = EXCLUDED.chat_id, user_name = EXCLUDED.user_name
        ''', (user_id, chat_id, user_name))
        conn.commit()
        cursor.close()
    finally:
        conn.close()

def register_group(user_id, group_chat_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO user_groups (user_id, group_chat_id) 
            VALUES (%s, %s) 
            ON CONFLICT (user_id) DO UPDATE SET group_chat_id = EXCLUDED.group_chat_id
        ''', (user_id, group_chat_id))
        conn.commit()
        cursor.close()
    finally:
        conn.close()

def get_categories(user_id):
    default_cats = ["Study", "Meal", "Snack", "Grocery", "Movie/Series", "Commute", "Exercises", "Sleep"]
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT category FROM categories WHERE user_id = %s", (user_id,))
        rows = cursor.fetchall()
        cursor.close()
        return [r['category'] for r in rows] if rows else default_cats
    finally:
        conn.close()

def add_batch_categories(user_id, categories_list):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT category FROM categories WHERE user_id = %s", (user_id,))
        if not cursor.fetchall():
            for cat in get_categories(user_id):
                cursor.execute("INSERT INTO categories VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, cat))
        
        for category in categories_list:
            category = category.strip()
            if category:
                cursor.execute("INSERT INTO categories VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, category))
        conn.commit()
        cursor.close()
    finally:
        conn.close()

def delete_category(user_id, category):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT category FROM categories WHERE user_id = %s", (user_id,))
        if not cursor.fetchall():
            for cat in get_categories(user_id):
                cursor.execute("INSERT INTO categories VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, cat))
        
        cursor.execute("DELETE FROM categories WHERE user_id = %s AND category = %s", (user_id, category.strip()))
        conn.commit()
        cursor.close()
    finally:
        conn.close()

def rename_category(user_id, old_name, new_name):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT category FROM categories WHERE user_id = %s", (user_id,))
        if not cursor.fetchall():
            for cat in get_categories(user_id):
                cursor.execute("INSERT INTO categories VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, cat))
                
        cursor.execute("UPDATE categories SET category = %s WHERE user_id = %s AND category = %s", (new_name.strip(), user_id, old_name.strip()))
        conn.commit()
        cursor.close()
    finally:
        conn.close()

def start_new_activity(user_id, chat_id, category):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        now = datetime.now()
        
        cursor.execute('SELECT id, start_time, category FROM activities WHERE user_id = %s AND end_time IS NULL ORDER BY id DESC LIMIT 1', (user_id,))
        last_act = cursor.fetchone()
        
        prev_info = None
        if last_act:
            act_id, start_dt = last_act['id'], last_act['start_time']
            duration = int((now - start_dt).total_seconds() / 60)
            cursor.execute('UPDATE activities SET end_time = %s, duration_minutes = %s WHERE id = %s', (now, duration, act_id))
            prev_info = {"category": last_act['category'], "duration": duration}
        
        cursor.execute('INSERT INTO activities (user_id, chat_id, category, start_time) VALUES (%s, %s, %s, %s)', (user_id, chat_id, category.strip(), now))
        conn.commit()
        cursor.close()
        return prev_info
    finally:
        conn.close()

def cancel_active_activity(user_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT id, category FROM activities WHERE user_id = %s AND end_time IS NULL ORDER BY id DESC LIMIT 1', (user_id,))
        row = cursor.fetchone()
        
        if row:
            act_id, category = row['id'], row['category']
            cursor.execute('DELETE FROM activities WHERE id = %s', (act_id,))
            conn.commit()
            cursor.close()
            return category
        cursor.close()
        return None
    finally:
        conn.close()

def get_current_session(user_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT category, start_time FROM activities WHERE user_id = %s AND end_time IS NULL ORDER BY id DESC LIMIT 1', (user_id,))
        row = cursor.fetchone()
        cursor.close()
        
        if row:
            start_dt = row['start_time']
            duration = int((datetime.now() - start_dt).total_seconds() / 60)
            return {"category": row['category'], "duration": duration}
        return None
    finally:
        conn.close()

def get_day_report_so_far(user_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        cursor.execute('''
            SELECT category, SUM(duration_minutes) as total_m
            FROM activities 
            WHERE user_id = %s AND start_time >= %s AND duration_minutes IS NOT NULL 
            GROUP BY category
        ''', (user_id, today_start))
        rows = cursor.fetchall()
        
        totals = {r['category']: r['total_m'] for r in rows}
        
        cursor.execute('SELECT category, start_time FROM activities WHERE user_id = %s AND end_time IS NULL ORDER BY id DESC LIMIT 1', (user_id,))
        active = cursor.fetchone()
        if active:
            start_dt = active['start_time']
            if start_dt >= today_start:
                active_duration = int((datetime.now() - start_dt).total_seconds() / 60)
                totals[active['category']] = totals.get(active['category'], 0) + active_duration
                
        cursor.close()
        return totals
    finally:
        conn.close()

def get_report(user_id, days):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        since_date = datetime.now() - timedelta(days=days)
        cursor.execute('''
            SELECT category, SUM(duration_minutes) as total_m 
            FROM activities 
            WHERE user_id = %s AND start_time >= %s AND duration_minutes IS NOT NULL 
            GROUP BY category
        ''', (user_id, since_date))
        rows = cursor.fetchall()
        cursor.close()
        
        if not rows: return "None\n"
        return "".join([f"• {r['category']}: {r['total_m'] // 60}h {r['total_m'] % 60}m\n" for r in rows])
    finally:
        conn.close()
