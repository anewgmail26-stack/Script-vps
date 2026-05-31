import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger("vps_manager")

def get_db_connection(db_path):
    """
    Establishes and returns a database connection.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path):
    """
    Initializes the database schema if it doesn't already exist.
    """
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,                  -- 'vless' or 'ssh'
            username TEXT,                       -- Client remark or SSH username
            uuid TEXT UNIQUE,                    -- VLESS client UUID
            password TEXT,                       -- SSH Password (null for vless)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            traffic_limit_bytes INTEGER NOT NULL, -- -1 for unlimited
            traffic_used_bytes INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            suspension_reason TEXT,
            xray_uplink_last INTEGER DEFAULT 0,  -- Last recorded uplink value from stats
            xray_downlink_last INTEGER DEFAULT 0 -- Last recorded downlink value from stats
        )
        """)
        conn.commit()
        conn.close()
        logger.info(f"Database successfully initialized at {db_path}.")
        return True
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return False

def add_vless_user(db_path, username, uuid, expires_at, traffic_limit_bytes):
    """
    Adds a new VLESS user to the database.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO users (type, username, uuid, expires_at, traffic_limit_bytes, is_active)
        VALUES ('vless', ?, ?, ?, ?, 1)
        """, (username, uuid, expires_at.isoformat(), traffic_limit_bytes))
        conn.commit()
        logger.info(f"VLESS user '{username}' ({uuid}) added to database.")
        return True
    except sqlite3.IntegrityError as e:
        logger.error(f"Failed to add VLESS user '{username}' due to integrity constraint: {e}")
        return False
    except Exception as e:
        logger.error(f"Error adding VLESS user to database: {e}")
        return False
    finally:
        conn.close()

def add_ssh_user(db_path, username, password, expires_at, traffic_limit_bytes):
    """
    Adds a new SSH user to the database.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO users (type, username, password, expires_at, traffic_limit_bytes, is_active)
        VALUES ('ssh', ?, ?, ?, ?, 1)
        """, (username, password, expires_at.isoformat(), traffic_limit_bytes))
        conn.commit()
        logger.info(f"SSH user '{username}' added to database.")
        return True
    except sqlite3.IntegrityError as e:
        logger.error(f"Failed to add SSH user '{username}' due to integrity constraint: {e}")
        return False
    except Exception as e:
        logger.error(f"Error adding SSH user to database: {e}")
        return False
    finally:
        conn.close()

def get_active_users(db_path):
    """
    Fetches all active users from the database.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE is_active = 1")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching active users: {e}")
        return []
    finally:
        conn.close()

def get_active_vless_users(db_path):
    """
    Fetches all active VLESS users.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE type = 'vless' AND is_active = 1")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching active VLESS users: {e}")
        return []
    finally:
        conn.close()

def get_all_users(db_path):
    """
    Fetches all users from the database.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching all users: {e}")
        return []
    finally:
        conn.close()

def get_user_by_uuid(db_path, uuid):
    """
    Retrieves a single user by VLESS UUID.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE uuid = ?", (uuid,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error fetching user by UUID '{uuid}': {e}")
        return None
    finally:
        conn.close()

def get_user_by_username(db_path, username, user_type):
    """
    Retrieves a single user by their username and type.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE username = ? AND type = ?", (username, user_type))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error fetching user by username '{username}': {e}")
        return None
    finally:
        conn.close()

def delete_user_by_uuid(db_path, uuid):
    """
    Deletes a user from the database by VLESS UUID, returning their info.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE uuid = ?", (uuid,))
        row = cursor.fetchone()
        if row:
            cursor.execute("DELETE FROM users WHERE uuid = ?", (uuid,))
            conn.commit()
            logger.info(f"VLESS user '{row['username']}' ({uuid}) deleted from database.")
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"Error deleting user by UUID '{uuid}': {e}")
        return None
    finally:
        conn.close()

def delete_user_by_username(db_path, username, user_type):
    """
    Deletes a user from the database by username and type, returning their info.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE username = ? AND type = ?", (username, user_type))
        row = cursor.fetchone()
        if row:
            cursor.execute("DELETE FROM users WHERE username = ? AND type = ?", (username, user_type))
            conn.commit()
            logger.info(f"User '{username}' ({user_type}) deleted from database.")
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"Error deleting user by username '{username}': {e}")
        return None
    finally:
        conn.close()

def suspend_user(db_path, user_id, reason):
    """
    Suspends a user by ID and records a reason.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
        UPDATE users SET is_active = 0, suspension_reason = ? WHERE id = ?
        """, (reason, user_id))
        conn.commit()
        logger.info(f"User ID {user_id} suspended in database. Reason: {reason}.")
        return True
    except Exception as e:
        logger.error(f"Error suspending user ID {user_id}: {e}")
        return False
    finally:
        conn.close()

def unsuspend_user(db_path, user_id):
    """
    Unsuspends a user by ID and clears counters.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
        UPDATE users 
        SET is_active = 1, suspension_reason = NULL, xray_uplink_last = 0, xray_downlink_last = 0 
        WHERE id = ?
        """, (user_id,))
        conn.commit()
        logger.info(f"User ID {user_id} unsuspended in database.")
        return True
    except Exception as e:
        logger.error(f"Error unsuspending user ID {user_id}: {e}")
        return False
    finally:
        conn.close()

def update_traffic(db_path, user_id, traffic_used_bytes, uplink_last, downlink_last):
    """
    Updates cumulative traffic and caches the last query values.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
        UPDATE users 
        SET traffic_used_bytes = ?, xray_uplink_last = ?, xray_downlink_last = ? 
        WHERE id = ?
        """, (traffic_used_bytes, uplink_last, downlink_last, user_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating traffic for user ID {user_id}: {e}")
        return False
    finally:
        conn.close()
