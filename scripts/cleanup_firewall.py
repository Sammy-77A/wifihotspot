"""
Cleanup script for Windows Firewall and MyPublicWiFi AutoLogins.
Removes any stale per-device block rules and unblocks captive portal redirection.
"""

import sqlite3
import subprocess
import os

MYPUBLICWIFI_DB = r"C:\Program Files (x86)\MyPublicWiFi\Data.db"


def cleanup_firewall():
    try:
        res = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=all"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        cleaned = 0
        for line in res.stdout.splitlines():
            if "WiFiPortal_Block" in line and ":" in line:
                rname = line.split(":", 1)[1].strip()
                del_res = subprocess.run(
                    ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={rname}"],
                    capture_output=True,
                    text=True,
                )
                if "Ok." in del_res.stdout or del_res.returncode == 0:
                    cleaned += 1
                    print(f"[OK] Deleted firewall rule: {rname}")
                else:
                    print(f"[NOTICE] Could not delete {rname}: {del_res.stdout.strip()}")
        if cleaned == 0:
            print("[OK] No stale WiFiPortal_Block firewall rules found.")
    except Exception as e:
        print(f"[NOTICE] Firewall check: {e}")


def cleanup_autologins():
    if not os.path.exists(MYPUBLICWIFI_DB):
        return
    try:
        conn = sqlite3.connect(MYPUBLICWIFI_DB, timeout=3.0)
        c = conn.cursor()
        c.execute("DELETE FROM AutoLogins")
        conn.commit()
        conn.close()
        print("[OK] Purged stale AutoLogins from MyPublicWiFi Data.db.")
    except Exception as e:
        print(f"[NOTICE] AutoLogins cleanup: {e}")


if __name__ == "__main__":
    cleanup_firewall()
    cleanup_autologins()

