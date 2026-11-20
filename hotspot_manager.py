"""
Hotspot Session Manager for MyPublicWiFi
Manages device network access, dynamic voucher generation, and per-device session revocations.
"""

import os
import random
import sqlite3
import logging
import subprocess
from typing import Dict, Any, Optional

logger = logging.getLogger("hotspot_manager")

MYPUBLICWIFI_DB = r"C:\Program Files (x86)\MyPublicWiFi\Data.db"


def mac_to_mypublicwifi_bigint(mac: Optional[str]) -> Optional[int]:
    """
    Converts a standard MAC address (e.g. '3A:7A:35:02:D7:3A' or '3a-7a-35-02-d7-3a')
    to MyPublicWiFi's little-endian 64-bit BIGINT representation used in Data.db.
    """
    if not mac:
        return None
    try:
        clean = mac.replace(":", "").replace("-", "").strip()
        if len(clean) != 12:
            return None
        octets = [int(clean[i:i + 2], 16) for i in range(0, 12, 2)]
        return sum(b << (8 * i) for i, b in enumerate(octets))
    except Exception:
        return None


class HotspotManager:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.gateway_ip = self.config.get("gateway_ip", "192.168.5.1")
        self.mypublicwifi_db = self.config.get("mypublicwifi_db", MYPUBLICWIFI_DB)

    def create_voucher(self, minutes: int, session_id: str) -> Optional[str]:
        """
        Creates a time-limited voucher code directly in MyPublicWiFi CodeAccounts table.
        MyPublicWiFi natively tracks and enforces this time limit per-client.
        """
        if not os.path.exists(self.mypublicwifi_db):
            logger.warning(f"MyPublicWiFi database not found at {self.mypublicwifi_db}")
            return None

        # Voucher format: e.g. LUMO8492
        voucher_code = f"LUMO{random.randint(1000, 9999)}"
        try:
            conn = sqlite3.connect(self.mypublicwifi_db, timeout=3.0)
            conn.execute(
                """
                INSERT INTO CodeAccounts (
                    Code, Active, CreatedDate,
                    MinutesCreditLimited, MinutesCredit,
                    TimeStopAtLogout, FixedEndTimeEnabled,
                    BytesTrafficCreditLimited, ExpireFromFirstLogin,
                    FirstLoginExpireDays, MultiLoginEnabled,
                    MaxConcurrentLogins, AutoLogin, Comment
                ) VALUES (?, 1, CURRENT_TIMESTAMP, 1, ?, 0, 0, 0, 1, 1, 0, 1, 0, ?)
                """,
                (voucher_code, int(minutes), f"Session {session_id}"),
            )
            conn.commit()
            conn.close()
            logger.info(f"Created MyPublicWiFi voucher '{voucher_code}' for {minutes} min (Session {session_id})")
            return voucher_code
        except Exception as e:
            logger.warning(f"Could not insert voucher into MyPublicWiFi Data.db: {e}")
            return None

    def unlock_client(
        self,
        client_mac: str,
        client_ip: str,
        duration_seconds: int,
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Grants internet access to client device.
        Generates a native MyPublicWiFi Voucher with an exact countdown timer.
        """
        logger.info(f"Unlocking client MAC={client_mac}, IP={client_ip} for {duration_seconds}s (Session {session_id})")

        # 1. Clear any prior Windows Firewall block for this specific IP
        self._remove_block_firewall_rule(client_ip)

        # 2. Generate native MyPublicWiFi voucher with exact minute duration
        minutes = max(1, int(duration_seconds // 60))
        voucher_code = self.create_voucher(minutes=minutes, session_id=session_id)

        if voucher_code:
            return {
                "success": True,
                "mode": "mypublicwifi_voucher",
                "action": "VoucherLogin",
                "voucher_code": voucher_code,
                "duration_minutes": minutes,
                "gateway_url": f"http://{self.gateway_ip}/",
                "message": f"Access unlocked for {minutes} minutes via native voucher {voucher_code}.",
            }

        # Fallback to TOCLogin if voucher creation failed
        return {
            "success": True,
            "mode": "mypublicwifi_toc",
            "action": "TOCLogin",
            "voucher_code": None,
            "duration_minutes": minutes,
            "gateway_url": f"http://{self.gateway_ip}/",
            "message": "Access unlocked. Submitting native MyPublicWiFi login action.",
        }

    def revoke_client(
        self,
        client_mac: str,
        client_ip: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Revokes internet access strictly for this specific client when their plan expires.
        Does NOT affect other connected users.
        """
        logger.info(f"Revoking internet access strictly for client MAC={client_mac}, IP={client_ip}")

        # 1. Clean up from MyPublicWiFi Sessions AND AutoLogins table using little-endian BIGINT and string MAC
        if os.path.exists(self.mypublicwifi_db):
            try:
                conn = sqlite3.connect(self.mypublicwifi_db, timeout=2.0)
                mac_int = mac_to_mypublicwifi_bigint(client_mac)
                if mac_int is not None:
                    conn.execute("DELETE FROM Sessions WHERE MAC = ?", (mac_int,))
                    conn.execute("DELETE FROM AutoLogins WHERE MAC = ?", (mac_int,))
                mac_clean = client_mac.replace(":", "-").upper()
                conn.execute("DELETE FROM Sessions WHERE MAC = ? OR MAC = ?", (mac_clean, client_mac.upper()))
                conn.execute("DELETE FROM AutoLogins WHERE MAC = ? OR MAC = ?", (mac_clean, client_mac.upper()))

                # Deactivate any voucher code associated with this session
                if session_id:
                    conn.execute("UPDATE CodeAccounts SET Active = 0 WHERE Comment LIKE ?", (f"%{session_id}%",))

                conn.commit()
                conn.close()
                logger.info(f"Removed MAC {client_mac} (BIGINT: {mac_int}) from MyPublicWiFi Sessions and AutoLogins tables.")
            except Exception as e:
                logger.warning(f"Could not remove session/autologin from MyPublicWiFi Data.db: {e}")

        # 2. Ensure any lingering Windows Firewall block rules for this IP are cleared so captive portal probes work seamlessly
        self._remove_block_firewall_rule(client_ip)

        return {"success": True, "mode": "revoked"}

    def _add_block_firewall_rule(self, client_ip: str):
        """
        No-op: Native MyPublicWiFi packet filter isolates unauthenticated clients
        and transparently redirects HTTP to port 80 (login.html).
        External Windows Firewall rules are disabled to prevent dropping OS captive portal probes.
        """
        pass

    def _remove_block_firewall_rule(self, client_ip: str):
        """
        Removes any Windows Firewall block rule for this client IP if one exists.
        """
        if not client_ip or client_ip in ("127.0.0.1", "0.0.0.0"):
            return
        try:
            rule_name = f"WiFiPortal_Block_{client_ip.replace('.', '_')}"
            cmd = [
                "netsh", "advfirewall", "firewall", "delete", "rule",
                f"name={rule_name}",
            ]
            subprocess.run(cmd, capture_output=True, timeout=2.0, shell=False)
            logger.info(f"Removed Windows Firewall block rule for client {client_ip}")
        except Exception as e:
            logger.debug(f"Could not remove firewall block rule: {e}")

    @staticmethod
    def cleanup_all_block_firewall_rules():
        """
        Purges any lingering WiFiPortal_Block_* rules from Windows Firewall.
        """
        try:
            res = subprocess.run(
                ["netsh", "advfirewall", "firewall", "show", "rule", "name=all"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            for line in res.stdout.splitlines():
                if "WiFiPortal_Block" in line and ":" in line:
                    rname = line.split(":", 1)[1].strip()
                    subprocess.run(
                        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={rname}"],
                        capture_output=True,
                        timeout=2.0,
                    )
                    logger.info(f"Purged lingering firewall rule: {rname}")
        except Exception as e:
            logger.debug(f"Could not purge all firewall rules: {e}")
