import sqlite3
import secrets
import string

DB_PATH = "totaldown.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        key TEXT,
        uploads_count INTEGER DEFAULT 0,
        authorized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS access_keys (
        key TEXT PRIMARY KEY,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        used_by INTEGER,
        is_active INTEGER DEFAULT 1
    )""")
    conn.commit()
    conn.close()

def generate_key(length=10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "TD-" + "".join(secrets.choice(alphabet) for _ in range(length))

def create_key(admin_id: int) -> str:
    key = generate_key()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO access_keys (key, created_by) VALUES (?, ?)", (key, admin_id))
    conn.commit()
    conn.close()
    return key

def validate_and_assign_key(key: str, user_id: int, username: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT is_active, used_by FROM access_keys WHERE key = ?", (key,))
    row = c.fetchone()
    if not row or row[0] == 0 or row[1] is not None:
        conn.close()
        return False
    c.execute("UPDATE access_keys SET used_by = ? WHERE key = ?", (user_id, key))
    c.execute(
        "INSERT OR REPLACE INTO users (user_id, username, key) VALUES (?, ?, ?)",
        (user_id, username, key)
    )
    conn.commit()
    conn.close()
    return True

def is_authorized(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row is not None

def list_keys():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT key, used_by, is_active FROM access_keys ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return rows

def increment_uploads(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET uploads_count = uploads_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_user_stats(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT uploads_count, authorized_at FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row
