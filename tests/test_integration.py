"""
Integration & Unit Test Suite for WiFi Captive Portal
Tests database operations, device management, LumoGate adapter, Flask endpoints, and Cyzora polling.
"""

import os
import sys
import json
import time
import hmac
import hashlib
import unittest
import datetime

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import database
import device_manager
from hotspot_manager import HotspotManager
from app import app, CONFIG, cyzora_client


class TestCaptivePortal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use an isolated test database
        cls.orig_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(os.path.dirname(__file__), "test_wifi_portal.db")
        if os.path.exists(database.DB_PATH):
            os.remove(database.DB_PATH)
        database.init_db()

        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(database.DB_PATH):
            try:
                os.remove(database.DB_PATH)
            except Exception:
                pass
        database.DB_PATH = cls.orig_db_path

    # ------------------------------------------------------------------
    # 1. Database Operations Tests
    # ------------------------------------------------------------------
    def test_01_database_session_flow(self):
        sess_id = "TEST-SESSION-001"
        charge_id = "ch_test_12345"
        mac = "00:11:22:33:44:55"
        ip = "192.168.137.50"
        phone = "254712345678"

        # Create session
        created = database.create_session(
            session_id=sess_id,
            client_ip=ip,
            client_mac=mac,
            phone_number=phone,
            plan_id="1hr",
            plan_name="1 Hour Pass",
            amount_kes=10,
            duration_seconds=3600,
            idempotency_key=sess_id,
            charge_id=charge_id,
        )
        self.assertIsNotNone(created)
        self.assertEqual(created["status"], "pending")
        self.assertEqual(created["client_mac"], mac)

        # Lookup by charge_id
        found = database.get_session_by_charge_id(charge_id)
        self.assertIsNotNone(found)
        self.assertEqual(found["session_id"], sess_id)

        # Lookup active session should be None because it's pending
        active = database.get_active_session_by_mac(mac)
        self.assertIsNone(active)

        # Activate session
        activated = database.activate_session(charge_id)
        self.assertIsNotNone(activated)
        self.assertEqual(activated["status"], "active")
        self.assertIsNotNone(activated["activated_at"])
        self.assertIsNotNone(activated["expires_at"])

        # Lookup active session now
        active_now = database.get_active_session_by_mac(mac)
        self.assertIsNotNone(active_now)
        self.assertEqual(active_now["session_id"], sess_id)

        # Revoke session
        database.revoke_session(sess_id)
        revoked = database.get_session_by_id(sess_id)
        self.assertEqual(revoked["status"], "expired")
        self.assertIsNotNone(revoked["revoked_at"])

    # ------------------------------------------------------------------
    # 2. Device Manager & MAC Resolution Tests
    # ------------------------------------------------------------------
    def test_02_mac_normalization(self):
        self.assertEqual(device_manager.normalize_mac("aa-bb-cc-dd-ee-ff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(device_manager.normalize_mac("aabb.ccdd.eeff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(device_manager.normalize_mac("11:22:33:44:55:66"), "11:22:33:44:55:66")
        self.assertIsNone(device_manager.normalize_mac("invalid-mac"))

    def test_03_query_param_mac_extraction(self):
        args = {"client_mac": "00:AA:BB:CC:DD:EE", "url": "http://example.com"}
        mac = device_manager.get_mac_from_query_params(args)
        self.assertEqual(mac, "00:AA:BB:CC:DD:EE")

    def test_04_loopback_mac_resolution(self):
        mac = device_manager.resolve_mac_from_arp("127.0.0.1")
        self.assertEqual(mac, "02:00:00:00:00:01")

    # ------------------------------------------------------------------
    # 3. Hotspot Manager Tests
    # ------------------------------------------------------------------
    def test_05_hotspot_manager_unlock_revoke(self):
        config = {
            "gateway_ip": "192.168.5.1",
            "mypublicwifi_db": os.path.join(os.path.dirname(__file__), "test_mpw_data.db"),
        }
        manager = HotspotManager(config)
        unlock_res = manager.unlock_client("AA:BB:CC:DD:EE:FF", "192.168.5.100", 3600, "SESS-001")
        self.assertTrue(unlock_res["success"])
        self.assertIn(unlock_res["action"], ("VoucherLogin", "TOCLogin"))

        revoke_res = manager.revoke_client("AA:BB:CC:DD:EE:FF", "192.168.5.100", "SESS-001")
        self.assertTrue(revoke_res["success"])

    # ------------------------------------------------------------------
    # 4. Flask Application Endpoint Tests
    # ------------------------------------------------------------------
    def test_06_portal_page_get(self):
        response = self.client.get("/portal?mac=AA:11:22:33:44:55&ip=192.168.137.42")
        self.assertEqual(response.status_code, 200)
        self.assertIn(CONFIG["server"]["brand_name"].encode("utf-8"), response.data)
        self.assertIn(b"AA:11:22:33:44:55", response.data)

    def test_07_api_plans_endpoint(self):
        response = self.client.get("/api/plans")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data["success"])
        self.assertGreaterEqual(len(data["plans"]), 1)

    def test_08_create_charge_validation(self):
        # Invalid plan
        resp = self.client.post("/api/create-charge", json={"plan_id": "nonexistent", "phone": "0712345678"})
        self.assertEqual(resp.status_code, 400)

        # Invalid phone
        resp = self.client.post("/api/create-charge", json={"plan_id": "1hr", "phone": "12345"})
        self.assertEqual(resp.status_code, 400)

    def test_09_polling_endpoint(self):
        # Create a pending session
        sess_id = "TEST-POLL-001"
        charge_id = "ch_poll_test"
        database.create_session(
            session_id=sess_id,
            client_ip="192.168.137.88",
            client_mac="CC:DD:EE:11:22:33",
            phone_number="254712345678",
            plan_id="1hr",
            plan_name="1 Hour Pass",
            amount_kes=10,
            duration_seconds=3600,
            idempotency_key=sess_id,
            charge_id=charge_id,
        )

        # Query poll endpoint while pending (mock test or external status)
        resp = self.client.get(f"/api/charge-status/{charge_id}")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn("status", data)

        # Activate directly and poll again -> should return succeeded
        database.activate_session(charge_id)
        resp2 = self.client.get(f"/api/charge-status/{charge_id}")
        self.assertEqual(resp2.status_code, 200)
        data2 = json.loads(resp2.data)
        self.assertEqual(data2["status"], "succeeded")
        self.assertTrue(data2["access_granted"])

    # ------------------------------------------------------------------
    # 5. Webhook Signature Verification Tests
    # ------------------------------------------------------------------
    def test_10_webhook_signature_verification(self):
        secret = cyzora_client.webhook_secrets[0] if cyzora_client.webhook_secrets else "whsec_test"
        # Temporarily ensure a secret is set for test
        cyzora_client.webhook_secrets = [secret]

        payload = json.dumps({
            "event": "charge.succeeded",
            "data": {
                "id": "ch_webhook_test_123",
                "amount": 2500,
                "phone": "254712345678",
                "status": "succeeded",
            }
        }).encode("utf-8")

        # Valid HMAC signature
        valid_sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

        # Create session in DB to match
        database.create_session(
            session_id="SESS-WEBHOOK-123",
            client_ip="192.168.137.99",
            client_mac="99:88:77:66:55:44",
            phone_number="254712345678",
            plan_id="3hr",
            plan_name="3 Hours Pass",
            amount_kes=25,
            duration_seconds=10800,
            idempotency_key="SESS-WEBHOOK-123",
            charge_id="ch_webhook_test_123",
        )

        # Send valid webhook
        resp = self.client.post(
            "/webhook",
            data=payload,
            headers={"Content-Type": "application/json", "X-Cyzora-Signature": valid_sig},
        )
        self.assertEqual(resp.status_code, 200)

        # Verify session was activated
        session = database.get_session_by_charge_id("ch_webhook_test_123")
        self.assertEqual(session["status"], "active")

        # Send invalid signature
        resp_invalid = self.client.post(
            "/webhook",
            data=payload,
            headers={"Content-Type": "application/json", "X-Cyzora-Signature": "invalid_signature"},
        )
        self.assertEqual(resp_invalid.status_code, 401)


if __name__ == "__main__":
    unittest.main()

