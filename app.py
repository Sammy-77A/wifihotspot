"""
WiFi Captive Portal Backend Server
Integrated with Cyzora M-Pesa STK Push and MyPublicWiFi Hotspot.
"""

import os
import json
import uuid
import logging
import datetime
from typing import Optional, Dict, Any
from flask import Flask, request, jsonify, render_template, redirect, url_for

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Cyzora SDK
from cyzora import Cyzora, CyzoraError, normalize_phone

# Internal modules
import database
import device_manager
from hotspot_manager import HotspotManager
from session_manager import start_background_worker

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("wifi_portal")

# Flask app initialization
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "wifi_hotspot_default_secret")


@app.after_request
def add_cors_headers(response):
    """Enable CORS so MyPublicWiFi Web portal can talk to Flask backend."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization,X-Requested-With"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response

# Load configuration
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Configuration file not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


CONFIG = load_config()

# Initialize Cyzora Client from Environment Variables
CYZORA_SECRET_KEY = os.getenv("CYZORA_SECRET_KEY", "").strip() or CONFIG.get("cyzora", {}).get("secret_key", "sk_test_placeholder")
CYZORA_WEBHOOK_SECRET = os.getenv("CYZORA_WEBHOOK_SECRET", "").strip() or None
CYZORA_BASE_URL = os.getenv("CYZORA_BASE_URL", "").strip() or "https://api.cyzora.co.ke/api/v1"

cyzora_client = Cyzora(
    secret_key=CYZORA_SECRET_KEY,
    webhook_secret=CYZORA_WEBHOOK_SECRET,
    base_url=CYZORA_BASE_URL,
)

# Initialize Hotspot Session Manager
hotspot_manager = HotspotManager(CONFIG.get("hotspot", {}))

# Start background session expiry worker
start_background_worker(CONFIG.get("hotspot", {}), interval_seconds=15)


def get_plan_by_id(plan_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves plan details from config."""
    for p in CONFIG.get("plans", []):
        if p["id"] == plan_id:
            return p
    return None


# ----------------------------------------------------------------------
# Captive Portal Splash Pages
# ----------------------------------------------------------------------
@app.route("/", methods=["GET"])
@app.route("/portal", methods=["GET"])
@app.route("/login", methods=["GET"])
def portal_page():
    """
    Renders the captive portal landing page for connected clients.
    """
    client_info = device_manager.get_client_device_info(request)
    client_ip = client_info["ip"]
    client_mac = client_info["mac"]
    gateway_url = client_info.get("gateway_url") or "http://www.google.com"

    # Check if client already has an active session
    active_session = None
    if client_mac:
        active_session = database.get_active_session_by_mac(client_mac)
    if not active_session and client_ip:
        active_session = database.get_active_session_by_ip(client_ip)

    remaining_seconds = 0
    if active_session and active_session.get("expires_at"):
        try:
            exp = datetime.datetime.fromisoformat(active_session["expires_at"])
            # Handle tz-aware vs naive
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=datetime.timezone.utc)
            remaining_seconds = max(0, int((exp - now_utc).total_seconds()))
        except Exception:
            remaining_seconds = 0

    return render_template(
        "index.html",
        brand_name=CONFIG["server"].get("brand_name", "LumoSpeed WiFi"),
        brand_tagline=CONFIG["server"].get("brand_tagline", "Instant High-Speed Internet Access"),
        support_phone=CONFIG["server"].get("support_phone", "0700 000 000"),
        plans=CONFIG.get("plans", []),
        client_ip=client_ip,
        client_mac=client_mac,
        gateway_url=gateway_url,
        active_session=active_session,
        remaining_seconds=remaining_seconds,
    )


# ----------------------------------------------------------------------
# Captive Portal Probe Detection (Android / iOS / Windows RFC 8910)
# ----------------------------------------------------------------------
@app.route("/generate_204", methods=["GET"])
@app.route("/gen_204", methods=["GET"])
@app.route("/hotspot-detect.html", methods=["GET"])
@app.route("/ncsi.txt", methods=["GET"])
@app.route("/connecttest.txt", methods=["GET"])
def captive_probe():
    """
    Handles OS captive portal auto-detection probes.
    If device is already active, return HTTP 204 (No Content) to signal internet is ready.
    If unauthenticated, redirect to portal landing page.
    """
    client_info = device_manager.get_client_device_info(request)
    active_session = database.get_active_session_by_mac(client_info["mac"])
    if active_session:
        return ("", 204)
    return redirect(url_for("portal_page", **request.args))


# ----------------------------------------------------------------------
# API Endpoints
# ----------------------------------------------------------------------
@app.route("/api/plans", methods=["GET"])
def api_plans():
    """Returns available data plans from config."""
    return jsonify({"success": True, "plans": CONFIG.get("plans", [])})


@app.route("/api/device-info", methods=["GET"])
def api_device_info():
    """Returns detected IP, MAC, and active session if present."""
    client_info = device_manager.get_client_device_info(request)
    client_mac = client_info["mac"]
    active_session = database.get_active_session_by_mac(client_mac)
    return jsonify({
        "success": True,
        "ip": client_info["ip"],
        "mac": client_mac,
        "active_session": active_session,
    })


@app.route("/api/check-session", methods=["GET"])
def api_check_session():
    """
    Allows a connected device or UI to check its current access status.
    """
    client_info = device_manager.get_client_device_info(request)
    client_mac = client_info["mac"]
    client_ip = client_info["ip"]

    session = None
    if client_mac:
        session = database.get_active_session_by_mac(client_mac)
    if not session and client_ip:
        session = database.get_active_session_by_ip(client_ip)

    if session and session.get("status") == "active":
        try:
            exp = datetime.datetime.fromisoformat(session["expires_at"])
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=datetime.timezone.utc)
            remaining = max(0, int((exp - now_utc).total_seconds()))
        except Exception:
            remaining = 0
        return jsonify({
            "active": True,
            "session_id": session["session_id"],
            "plan_name": session["plan_name"],
            "expires_at": session["expires_at"],
            "remaining_seconds": remaining,
        })

    return jsonify({"active": False})


@app.route("/api/create-charge", methods=["POST"])
def api_create_charge():
    """
    Initiates an M-Pesa STK Push payment via Cyzora SDK.
    Creates a pending session in SQLite.
    """
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    plan_id = data.get("plan_id")
    phone_raw = data.get("phone")
    client_mac = device_manager.normalize_mac(data.get("mac"))
    client_ip = data.get("ip") or request.remote_addr
    gateway_url = data.get("gateway_url")

    # 1. Validate plan
    plan = get_plan_by_id(plan_id)
    if not plan:
        return jsonify({"success": False, "error": "Invalid or missing data plan."}), 400

    # 2. Validate and normalize phone number
    normalized_phone = normalize_phone(phone_raw)
    if not normalized_phone:
        return jsonify({
            "success": False,
            "error": "Please enter a valid Safaricom/Airtel phone number (e.g. 0712 345 678 or 254712345678)."
        }), 400

    # 3. Resolve MAC if missing
    if not client_mac:
        client_info = device_manager.get_client_device_info(request)
        client_mac = client_info["mac"]

    # 4. Generate unique session ID & Idempotency Key
    session_id = f"WIFI-{uuid.uuid4().hex[:10].upper()}"
    idempotency_key = session_id
    amount_kes = int(plan["price_kes"])

    # 5. Record pending session in SQLite
    database.create_session(
        session_id=session_id,
        client_ip=client_ip,
        client_mac=client_mac,
        phone_number=normalized_phone,
        plan_id=plan["id"],
        plan_name=plan["name"],
        amount_kes=amount_kes,
        duration_seconds=plan["duration_seconds"],
        idempotency_key=idempotency_key,
        gateway_url=gateway_url,
    )
    database.log_audit("charge_initiated", session_id, client_mac, f"Plan {plan['name']} (KES {amount_kes}) for phone {normalized_phone}")

    # 6. Trigger Cyzora STK Push
    try:
        charge_resp = cyzora_client.create_charge(
            amount_kes=amount_kes,
            phone=normalized_phone,
            network="mpesa",
            account_ref=session_id,
            description=f"{CONFIG['server'].get('brand_name', 'WiFi')} {plan['name']}",
            idempotency_key=idempotency_key,
        )
        logger.info(f"Cyzora create_charge response: {charge_resp}")

        # Extract charge ID safely
        charge_id = None
        if isinstance(charge_resp, dict):
            charge_id = charge_resp.get("id") or charge_resp.get("charge_id") or (charge_resp.get("data") or {}).get("id")
        
        if not charge_id:
            # Fallback charge id for dev/mock environments
            charge_id = f"ch_{session_id}"

        database.update_charge_id(session_id, charge_id)

        return jsonify({
            "success": True,
            "session_id": session_id,
            "charge_id": charge_id,
            "amount_kes": amount_kes,
            "phone": normalized_phone,
            "plan_name": plan["name"],
            "message": f"STK Push sent to {normalized_phone}! Check your phone and enter your M-Pesa PIN.",
        })

    except CyzoraError as e:
        logger.error(f"Cyzora API Error: {e.message} (status: {e.status})")
        return jsonify({
            "success": False,
            "error": f"Payment system error: {e.message}"
        }), 502

    except Exception as e:
        logger.error(f"Unexpected error creating charge: {e}")
        return jsonify({
            "success": False,
            "error": f"Could not initiate payment: {str(e)}"
        }), 500


@app.route("/api/charge-status/<charge_id>", methods=["GET"])
def api_charge_status(charge_id: str):
    """
    Pure local polling endpoint polled every 3 seconds by the client portal.
    Checks SQLite status first. If pending, queries Cyzora rail.
    On payment success, activates session and unlocks hotspot access.
    """
    session = database.get_session_by_charge_id(charge_id)
    if not session:
        return jsonify({"success": False, "error": "Session not found."}), 404

    # Case 1: Session is already active (e.g. activated by webhook or prior poll)
    if session["status"] == "active":
        voucher = session.get("voucher_code")
        return jsonify({
            "status": "succeeded",
            "access_granted": True,
            "message": "Payment verified! Your internet access is active.",
            "session_id": session["session_id"],
            "plan_name": session["plan_name"],
            "activated_at": session["activated_at"],
            "expires_at": session["expires_at"],
            "gateway_url": session.get("gateway_url") or "http://www.google.com",
            "voucher_code": voucher,
            "action": "VoucherLogin" if voucher else "TOCLogin",
        })

    # Case 2: Session failed or expired
    if session["status"] in ("failed", "expired"):
        return jsonify({
            "status": session["status"],
            "access_granted": False,
            "message": "Payment was not completed or expired. Please try again.",
        })

    # Case 3: Still pending in SQLite -> Poll Cyzora API
    try:
        remote_charge = cyzora_client.get_charge(charge_id)
        logger.info(f"Polled Cyzora status for {charge_id}: {remote_charge}")

        charge_data = remote_charge if isinstance(remote_charge, dict) else {}
        status = str(charge_data.get("status", "")).lower()

        if status in ("succeeded", "paid", "success", "completed"):
            # 1. Activate session in DB
            activated_session = database.activate_session(charge_id)
            if not activated_session:
                activated_session = session

            # 2. Unlock in Hotspot Manager
            unlock_res = hotspot_manager.unlock_client(
                client_mac=session["client_mac"],
                client_ip=session["client_ip"],
                duration_seconds=session["duration_seconds"],
                session_id=session["session_id"],
            )

            # 3. Store voucher code if created
            voucher_code = unlock_res.get("voucher_code")
            if voucher_code:
                database.update_voucher_code(session["session_id"], voucher_code)

            return jsonify({
                "status": "succeeded",
                "access_granted": True,
                "message": "Payment confirmed! Internet unlocked.",
                "session_id": session["session_id"],
                "plan_name": session["plan_name"],
                "activated_at": activated_session.get("activated_at"),
                "expires_at": activated_session.get("expires_at"),
                "gateway_url": session.get("gateway_url") or "http://www.google.com",
                "client_redirect_url": unlock_res.get("client_redirect_url"),
                "voucher_code": voucher_code,
                "action": unlock_res.get("action", "VoucherLogin" if voucher_code else "TOCLogin"),
            })

        elif status in ("failed", "cancelled", "declined"):
            database.mark_session_failed(charge_id, reason=f"Cyzora returned {status}")
            return jsonify({
                "status": "failed",
                "access_granted": False,
                "message": "Payment was declined or cancelled on your phone.",
            })

        elif status in ("expired", "timeout"):
            database.mark_session_failed(charge_id, reason="STK prompt timed out")
            return jsonify({
                "status": "expired",
                "access_granted": False,
                "message": "Payment prompt timed out. Please request a new pass.",
            })

        else:
            # Still pending
            return jsonify({
                "status": "pending",
                "access_granted": False,
                "message": "Awaiting M-Pesa PIN confirmation on your phone...",
            })

    except CyzoraError as e:
        logger.warning(f"Cyzora status check notice: {e.message}")
        return jsonify({
            "status": "pending",
            "access_granted": False,
            "message": "Checking payment status...",
        })
    except Exception as e:
        logger.error(f"Error querying charge {charge_id}: {e}")
        return jsonify({
            "status": "pending",
            "access_granted": False,
            "message": "Checking payment status...",
        })


# ----------------------------------------------------------------------
# Webhook Endpoint (HMAC-SHA256 Verified)
# ----------------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def cyzora_webhook():
    """
    Receives Cyzora payment webhooks (charge.succeeded, charge.failed, charge.expired).
    Verifies HMAC-SHA256 signature using raw request body.
    """
    raw_body = request.get_data()
    sig_header = (
        request.headers.get("X-Cyzora-Signature")
        or request.headers.get("Cyzora-Signature")
        or request.headers.get("X-Signature")
    )

    if not sig_header:
        logger.warning("Webhook received without signature header.")
        return jsonify({"error": "Missing signature header"}), 401

    try:
        event = cyzora_client.construct_webhook_event(raw_body, sig_header)
    except CyzoraError as e:
        logger.warning(f"Webhook signature verification failed: {e.message}")
        return jsonify({"error": "Invalid signature"}), 401
    except Exception as e:
        logger.error(f"Error parsing webhook event: {e}")
        return jsonify({"error": "Malformed webhook payload"}), 400

    event_type = event.get("event") or event.get("type")
    data = event.get("data") or {}
    charge_id = data.get("id") or data.get("charge_id")

    logger.info(f"Verified webhook event received: {event_type} for charge {charge_id}")

    if event_type == "charge.succeeded":
        session = database.get_session_by_charge_id(charge_id)
        if session:
            database.activate_session(charge_id)
            hotspot_manager.unlock_client(
                client_mac=session["client_mac"],
                client_ip=session["client_ip"],
                duration_seconds=session["duration_seconds"],
                session_id=session["session_id"],
            )
            logger.info(f"Webhook activated access for MAC {session['client_mac']}")

    elif event_type in ("charge.failed", "charge.expired"):
        database.mark_session_failed(charge_id, reason=f"Webhook event: {event_type}")

    return jsonify({"received": True, "event": event_type}), 200


def true_or_bool(val: bool) -> bool:
    return bool(val)


if __name__ == "__main__":
    host = CONFIG["server"].get("host", "0.0.0.0")
    port = int(CONFIG["server"].get("port", 5000))
    debug = bool(CONFIG["server"].get("debug", False))

    print("=" * 60)
    print(f"  {CONFIG['server'].get('brand_name', 'WiFi Captive Portal')} Server Running")
    print(f"  Access Portal locally: http://127.0.0.1:{port}")
    print(f"  Hotspot Subnet Portal: http://{CONFIG.get('hotspot', {}).get('gateway_ip', '192.168.5.1')}:{port}")
    print("=" * 60)

    app.run(host=host, port=port, debug=debug)
