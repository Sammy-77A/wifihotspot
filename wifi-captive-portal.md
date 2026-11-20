# Task Specification: WiFi Captive Portal with Cyzora M-Pesa Integration

## Overview
Automated payment-driven captive portal for Windows running MyPublicWiFi. Users connecting to the WiFi hotspot are redirected to a mobile-first portal, select a time-based data plan, receive an M-Pesa STK Push via Cyzora, and automatically receive internet access upon payment confirmation via polling (with webhook support included).

---

## Architecture Components

1. **Captive Portal Frontend (`mypublicwifi_portal.html`, `templates/index.html`)**
   - Pure HTML5 / CSS3 / Vanilla JavaScript (zero external CDN or JS framework dependencies for 100% offline captive portal compatibility).
   - Mobile-first, responsive, dark modern UI with live STK Push state polling every 3 seconds.
   - Shows connection status, active session status, plan selection, and M-Pesa phone number input.

2. **Backend Server (`app.py`)**
   - Lightweight Python Flask web server on port 5000.
   - Serves the portal splash page, handles plan listings from `config.json`.
   - Initiates STK Push using Cyzora SDK (`cyzora.Cyzora`).
   - Pure local polling endpoint `/api/charge-status/<charge_id>` for instant local unlock without port forwarding.
   - Webhook endpoint `/webhook` with HMAC-SHA256 signature verification.
   - Session restore endpoint `/api/check-session` to re-verify returning devices.

3. **Device & Network Identifier (`device_manager.py`)**
   - Extracts MAC and IP from query parameters or incoming sockets.
   - Automatically performs Windows ARP table lookup (`arp -a <client_ip>` and `Get-NetNeighbor`) to resolve the hardware MAC address.

4. **Hotspot Session Controller (`hotspot_manager.py`)**
   - Integrates directly with MyPublicWiFi's native `TOCLogin` unlock mechanism.
   - Enforces plan durations and revokes expired sessions.

5. **Session Management & Storage (`database.py`, `session_manager.py`)**
   - SQLite persistent database (`wifi_portal.db`) tracking sessions, phone numbers, plans, timestamps, and audit events.
   - Background daemon thread running every 15 seconds to detect expired sessions and revoke access.

6. **Configuration (`config.json`, `.env`)**
   - Separates all customizable variables (Cyzora API keys in `.env`, brand info and plans in `config.json`).
   - Allows changing plans/prices without touching code.

7. **Windows Auto-Start & Reboot Resilience (`scripts/`)**
   - `start_hotspot.bat`: Master batch launcher.
   - `link_mypublicwifi.bat`: Installs payment portal into MyPublicWiFi and configures firewall.
   - `restore_mypublicwifi.bat`: Restores original login page.
   - `install_autostart.ps1`: Registers Windows Task Scheduler job to run on system boot.
   - `stop_hotspot.bat`: Clean shutdown script.
