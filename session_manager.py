"""
Background Session Expiry Manager
Continuously scans the SQLite database for expired sessions and revokes hotspot access.
"""

import time
import threading
import logging
from typing import Optional
import database
from hotspot_manager import HotspotManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("session_manager")

_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def check_and_revoke_expired_sessions(manager: HotspotManager):
    """
    Finds all active sessions whose expiry time has passed and revokes them.
    """
    try:
        expired_sessions = database.get_expired_sessions()
        if expired_sessions:
            logger.info(f"Found {len(expired_sessions)} expired session(s) to revoke.")

        for session in expired_sessions:
            sess_id = session["session_id"]
            mac = session["client_mac"]
            ip = session["client_ip"]
            plan_name = session["plan_name"]
            phone = session["phone_number"]

            logger.info(f"Revoking access for {mac} ({ip}) - Plan: {plan_name}, Phone: {phone}")

            # 1. Inform Hotspot Manager to revoke
            try:
                manager.revoke_client(client_mac=mac, client_ip=ip, session_id=sess_id)
            except Exception as e:
                logger.error(f"Error revoking access for {mac}: {e}")

            # 2. Mark session as expired in database
            database.revoke_session(sess_id)

            # 3. Log audit event
            database.log_audit(
                event_type="access_revoked",
                session_id=sess_id,
                client_mac=mac,
                details=f"Session expired automatically. Duration completed for plan {plan_name}.",
            )
            logger.info(f"Session {sess_id} for MAC {mac} revoked successfully.")

        # 4. Sync with MyPublicWiFi to purge any lingering sessions not active in SQLite
        sync_active_sessions_with_mypublicwifi(manager)

    except Exception as e:
        logger.error(f"Error in session revocation check: {e}")


def sync_active_sessions_with_mypublicwifi(manager: HotspotManager):
    """
    Cleans up any expired or zombie sessions and AutoLogins from MyPublicWiFi Data.db that are not active in SQLite.
    Prevents sessions from persisting past their expiration and ensures the captive portal immediately reappears.
    """
    import os
    import sqlite3
    from hotspot_manager import mac_to_mypublicwifi_bigint

    if not os.path.exists(manager.mypublicwifi_db):
        return

    try:
        active_sessions = database.get_all_active_sessions()
        active_mac_ints = {
            mac_to_mypublicwifi_bigint(s["client_mac"])
            for s in active_sessions
            if s.get("client_mac")
        }
        active_mac_ints.discard(None)

        conn = sqlite3.connect(manager.mypublicwifi_db, timeout=2.0)
        c = conn.cursor()

        # 1. Purge inactive sessions from Sessions table
        mpw_sessions = c.execute("SELECT MAC FROM Sessions").fetchall()
        for (mpw_mac,) in mpw_sessions:
            if mpw_mac not in active_mac_ints:
                logger.info(f"Purging expired session MAC={mpw_mac} from MyPublicWiFi Sessions table.")
                c.execute("DELETE FROM Sessions WHERE MAC = ?", (mpw_mac,))

        # 2. Purge inactive AutoLogins so MyPublicWiFi never suppresses the captive portal
        mpw_autologins = c.execute("SELECT MAC FROM AutoLogins").fetchall()
        for (al_mac,) in mpw_autologins:
            if al_mac not in active_mac_ints:
                logger.info(f"Purging expired AutoLogin MAC={al_mac} from MyPublicWiFi AutoLogins table.")
                c.execute("DELETE FROM AutoLogins WHERE MAC = ?", (al_mac,))

        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"Session sync notice: {e}")


def worker_loop(manager: HotspotManager, interval_seconds: int = 15):
    """
    Daemon loop running in the background.
    """
    logger.info(f"Session Expiry Worker started (scan interval: {interval_seconds}s).")
    # Clean up any lingering block firewall rules on startup
    manager.cleanup_all_block_firewall_rules()

    while not _stop_event.is_set():
        check_and_revoke_expired_sessions(manager)
        # Sleep in small increments for responsive shutdown
        for _ in range(interval_seconds):
            if _stop_event.is_set():
                break
            time.sleep(1)
    logger.info("Session Expiry Worker stopped.")


def start_background_worker(hotspot_config: Optional[dict] = None, interval_seconds: int = 15):
    """
    Spawns the background worker daemon thread.
    """
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        logger.debug("Background worker already active.")
        return

    _stop_event.clear()
    manager = HotspotManager(hotspot_config)
    _worker_thread = threading.Thread(
        target=worker_loop,
        args=(manager, interval_seconds),
        daemon=True,
        name="SessionExpiryWorker",
    )
    _worker_thread.start()
    return _worker_thread


def stop_background_worker():
    """Stops the background worker thread."""
    _stop_event.set()
    if _worker_thread:
        _worker_thread.join(timeout=3.0)


if __name__ == "__main__":
    # If run directly as a standalone process
    import json
    import os

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    cfg = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    hotspot_cfg = cfg.get("hotspot", {})
    manager = HotspotManager(hotspot_cfg)
    try:
        worker_loop(manager, interval_seconds=10)
    except KeyboardInterrupt:
        logger.info("Exiting session manager.")

