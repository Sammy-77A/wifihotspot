"""
Cleanup script for Windows Firewall, adapter IP conflicts, and MyPublicWiFi AutoLogins.
Removes any stale per-device block rules and unblocks captive portal redirection.
"""

import sqlite3
import subprocess
import os
import winreg

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


def cleanup_adapter_ip_conflicts():
    """
    Cleans up conflicting multi-IP bindings on Wi-Fi Direct virtual adapters.
    Fixes 'IP configuration failure' on connected phones when switching between
    Windows Mobile Hotspot (192.168.137.x) and MyPublicWiFi (192.168.5.x).
    """
    interfaces_path = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, interfaces_path, 0, winreg.KEY_READ) as root_key:
            num_subkeys, _, _ = winreg.QueryInfoKey(root_key)
            for i in range(num_subkeys):
                subkey_name = winreg.EnumKey(root_key, i)
                subkey_path = f"{interfaces_path}\\{subkey_name}"
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        subkey_path,
                        0,
                        winreg.KEY_READ | winreg.KEY_SET_VALUE,
                    ) as key:
                        try:
                            ip_val, val_type = winreg.QueryValueEx(key, "IPAddress")
                            if isinstance(ip_val, (list, tuple)):
                                has_5 = any("192.168.5." in s for s in ip_val)
                                has_137 = any("192.168.137." in s for s in ip_val)
                                if has_5 and has_137:
                                    print(f"[FIX] Detected conflicting IPs on adapter {subkey_name}: {ip_val}")
                                    winreg.SetValueEx(key, "IPAddress", 0, winreg.REG_MULTI_SZ, ["0.0.0.0"])
                                    winreg.SetValueEx(key, "SubnetMask", 0, winreg.REG_MULTI_SZ, ["0.0.0.0"])
                                    winreg.SetValueEx(key, "EnableDHCP", 0, winreg.REG_DWORD, 1)
                                    print(f"[OK] Successfully reset adapter {subkey_name} to dynamic DHCP.")
                        except FileNotFoundError:
                            pass
                except PermissionError:
                    pass
    except Exception as e:
        print(f"[NOTICE] Adapter IP cleanup: {e}")


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
    cleanup_adapter_ip_conflicts()
    cleanup_autologins()


