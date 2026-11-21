"""
Device Identification & MAC Address Resolver for Windows WiFi Hotspot
Handles client IP detection and resolves MAC address via query params or Windows ARP cache.
"""

import re
import subprocess
import logging
from typing import Optional

logger = logging.getLogger("device_manager")

# Standard MAC regex pattern
MAC_PATTERN = re.compile(r"([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})")


def normalize_mac(mac_str: Optional[str]) -> Optional[str]:
    """
    Standardizes a MAC address string to XX:XX:XX:XX:XX:XX uppercase format.
    """
    if not mac_str:
        return None
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", str(mac_str))
    if len(cleaned) != 12:
        return None
    # Pair two hex digits and join with colons
    return ":".join(cleaned[i : i + 2].upper() for i in range(0, 12, 2))


def get_mac_from_query_params(args: dict) -> Optional[str]:
    """
    Checks common captive portal gateway query parameters for client MAC address.
    MyPublicWiFi, CoovaChilli, Mikrotik, and Cisco gateways pass one of these keys.
    """
    keys = ["mac", "client_mac", "usermac", "user_mac", "clientMac", "mac_address", "clientmac"]
    for k in keys:
        val = args.get(k)
        if val:
            normalized = normalize_mac(val)
            if normalized:
                return normalized
    return None


def resolve_mac_from_arp(ip_address: str) -> Optional[str]:
    """
    Resolves client MAC address from the Windows ARP cache using `arp -a <ip>`.
    Falls back to `Get-NetNeighbor` if needed.
    """
    if not ip_address:
        return None

    # Handle local loopback / testing
    if ip_address in ("127.0.0.1", "::1", "localhost"):
        return "02:00:00:00:00:01"

    # 1. Try Windows `arp -a <ip>`
    try:
        proc = subprocess.run(
            ["arp", "-a", ip_address],
            capture_output=True,
            text=True,
            timeout=2.0,
            shell=False,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if ip_address in line:
                    match = MAC_PATTERN.search(line)
                    if match:
                        normalized = normalize_mac(match.group(0))
                        if normalized and normalized != "FF:FF:FF:FF:FF:FF":
                            return normalized
    except Exception as e:
        logger.debug(f"arp -a failed for {ip_address}: {e}")

    # 2. If not found in ARP table, ping once to refresh ARP entry
    try:
        subprocess.run(
            ["ping", "-n", "1", "-w", "200", ip_address],
            capture_output=True,
            timeout=1.0,
            shell=False,
        )
        # Re-check arp -a
        proc = subprocess.run(
            ["arp", "-a", ip_address],
            capture_output=True,
            text=True,
            timeout=2.0,
            shell=False,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if ip_address in line:
                    match = MAC_PATTERN.search(line)
                    if match:
                        normalized = normalize_mac(match.group(0))
                        if normalized and normalized != "FF:FF:FF:FF:FF:FF":
                            return normalized
    except Exception:
        pass

    # 3. Fallback to PowerShell Get-NetNeighbor
    try:
        cmd = f"Get-NetNeighbor -IPAddress '{ip_address}' | Select-Object -ExpandProperty LinkLayerAddress"
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        if proc.returncode == 0:
            raw_output = proc.stdout.strip()
            if raw_output:
                normalized = normalize_mac(raw_output)
                if normalized and normalized != "FF:FF:FF:FF:FF:FF":
                    return normalized
    except Exception as e:
        logger.debug(f"Get-NetNeighbor failed: {e}")

    return None


def get_client_device_info(request) -> dict:
    """
    Extracts client IP and MAC address from the incoming Flask HTTP request.
    Strategy:
    1. Determine IP: request.headers 'X-Forwarded-For' or request.remote_addr.
    2. Check gateway URL query parameters for MAC.
    3. If absent, resolve MAC from Windows ARP cache using IP.
    """
    # 1. Client IP
    client_ip = request.remote_addr
    if request.headers.get("X-Forwarded-For"):
        client_ip = request.headers.get("X-Forwarded-For").split(",")[0].strip()

    # 2. Check query params first
    client_mac = get_mac_from_query_params(request.args)

    # 3. Fallback to Windows ARP resolution
    if not client_mac and client_ip:
        client_mac = resolve_mac_from_arp(client_ip)

    # 4. Fallback fallback if completely unreachable in development/isolated network
    if not client_mac:
        # Generate a deterministic pseudo-MAC based on IP for dev testing
        ip_parts = client_ip.replace(":", ".").split(".")
        hex_suffix = "".join(f"{int(p):02x}" for p in ip_parts[-3:] if p.isdigit())
        client_mac = f"02:00:00:{hex_suffix[:2] or '00'}:{hex_suffix[2:4] or '00'}:{hex_suffix[4:6] or '01'}".upper()

    return {
        "ip": client_ip,
        "mac": client_mac,
        "user_agent": request.headers.get("User-Agent", "Unknown"),
        "gateway_url": request.args.get("url") or request.args.get("dest") or request.args.get("orig_url")
    }


def get_client_ip(request) -> str:
    """Extracts client IP address from request."""
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def resolve_mac(request, ip_address: Optional[str] = None) -> str:
    """Extracts or resolves client MAC address from request or ARP cache."""
    info = get_client_device_info(request)
    if info.get("mac"):
        return info["mac"]
    if ip_address:
        mac = resolve_mac_from_arp(ip_address)
        if mac:
            return mac
    return "02:00:00:00:00:01"


