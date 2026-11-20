"""
SQLite Database Layer for WiFi Captive Portal
Manages client sessions, Cyzora charges, and audit logs.
"""

import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wifi_portal.db")


def get_utc_now() -> datetime:
    """Returns current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def get_utc_now_iso() -> str:
    """Returns current UTC datetime formatted as ISO string."""
    return get_utc_now().isoformat()


def get_db_connection() -> sqlite3.Connection:
    """Creates a connection to SQLite database with Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes tables and indexes if they do not exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Sessions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE NOT NULL,
        client_ip TEXT NOT NULL,
        client_mac TEXT NOT NULL,
        phone_number TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        plan_name TEXT NOT NULL,
        amount_kes INTEGER NOT NULL,
        duration_seconds INTEGER NOT NULL,
        charge_id TEXT UNIQUE,
        idempotency_key TEXT UNIQUE NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        gateway_url TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        activated_at TIMESTAMP,
        expires_at TIMESTAMP,
        revoked_at TIMESTAMP,
        voucher_code TEXT
    )
    """)

    # Ensure voucher_code column exists for existing databases
    try:
        cursor.execute("ALTER TABLE sessions ADD COLUMN voucher_code TEXT")
    except sqlite3.OperationalError:
        pass

    # Audit logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        session_id TEXT,
        client_mac TEXT,
        details TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Performance indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_charge_id ON sessions (charge_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_mac ON sessions (client_mac)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions (status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at)")

    conn.commit()
    conn.close()


def create_session(
    session_id: str,
    client_ip: str,
    client_mac: str,
    phone_number: str,
    plan_id: str,
    plan_name: str,
    amount_kes: int,
    duration_seconds: int,
    idempotency_key: str,
    gateway_url: Optional[str] = None,
    charge_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a new pending session record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO sessions (
            session_id, client_ip, client_mac, phone_number,
            plan_id, plan_name, amount_kes, duration_seconds,
            charge_id, idempotency_key, status, gateway_url, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            session_id,
            client_ip,
            client_mac,
            phone_number,
            plan_id,
            plan_name,
            amount_kes,
            duration_seconds,
            charge_id,
            idempotency_key,
            gateway_url,
            get_utc_now_iso(),
        ),
    )
    conn.commit()
    conn.close()
    return get_session_by_id(session_id)


def update_charge_id(session_id: str, charge_id: str):
    """Updates the charge_id associated with a session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE sessions SET charge_id = ? WHERE session_id = ?",
        (charge_id, session_id),
    )
    conn.commit()
    conn.close()


def update_voucher_code(session_id: str, voucher_code: str):
    """Updates the voucher_code associated with a session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE sessions SET voucher_code = ? WHERE session_id = ?",
        (voucher_code, session_id),
    )
    conn.commit()
    conn.close()


def get_session_by_id(session_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a session by session_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_session_by_charge_id(charge_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a session by Cyzora charge_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE charge_id = ?", (charge_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_active_session_by_mac(client_mac: str) -> Optional[Dict[str, Any]]:
    """
    Checks if a MAC address currently has an active non-expired session.
    """
    if not client_mac:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM sessions 
        WHERE client_mac = ? 
          AND status = 'active' 
          AND expires_at > ?
        ORDER BY expires_at DESC 
        LIMIT 1
        """,
        (client_mac.upper(), get_utc_now_iso()),
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_active_session_by_ip(client_ip: str) -> Optional[Dict[str, Any]]:
    """
    Checks if an IP address currently has an active non-expired session.
    """
    if not client_ip:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM sessions 
        WHERE client_ip = ? 
          AND status = 'active' 
          AND expires_at > ?
        ORDER BY expires_at DESC 
        LIMIT 1
        """,
        (client_ip, get_utc_now_iso()),
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_active_sessions() -> List[Dict[str, Any]]:
    """Returns all currently active non-expired sessions."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM sessions 
        WHERE status = 'active' 
          AND expires_at > ?
        """,
        (get_utc_now_iso(),),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def activate_session(charge_id: str) -> Optional[Dict[str, Any]]:
    """
    Activates a pending session upon payment success.
    Calculates expires_at based on duration_seconds.
    """
    session = get_session_by_charge_id(charge_id)
    if not session:
        return None

    if session["status"] == "active":
        return session  # Already activated

    now = get_utc_now()
    duration = timedelta(seconds=session["duration_seconds"])
    expires_at = now + duration

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE sessions
        SET status = 'active',
            activated_at = ?,
            expires_at = ?
        WHERE charge_id = ?
        """,
        (now.isoformat(), expires_at.isoformat(), charge_id),
    )
    conn.commit()
    conn.close()

    log_audit("payment_success", session["session_id"], session["client_mac"], f"Activated plan {session['plan_name']} until {expires_at.isoformat()}")
    return get_session_by_charge_id(charge_id)


def mark_session_failed(charge_id: str, reason: str = "Payment failed or expired"):
    """Marks a session as failed/expired."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE sessions SET status = 'failed' WHERE charge_id = ? AND status = 'pending'",
        (charge_id,),
    )
    conn.commit()
    conn.close()
    log_audit("payment_failed", None, None, f"Charge {charge_id} failed: {reason}")


def get_expired_sessions() -> List[Dict[str, Any]]:
    """Finds all active sessions whose expires_at is in the past."""
    now_iso = get_utc_now_iso()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM sessions WHERE status = 'active' AND expires_at <= ?",
        (now_iso,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def revoke_session(session_id: str):
    """Marks an expired session as revoked."""
    now_iso = get_utc_now_iso()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE sessions SET status = 'expired', revoked_at = ? WHERE session_id = ?",
        (now_iso, session_id),
    )
    conn.commit()
    conn.close()


def log_audit(event_type: str, session_id: Optional[str], client_mac: Optional[str], details: str):
    """Appends an event to the audit log."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO audit_logs (event_type, session_id, client_mac, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event_type,
                session_id,
                client_mac,
                details,
                get_utc_now_iso(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Audit Log Error] Failed to write log: {e}")


# Initialize DB on module import
init_db()
