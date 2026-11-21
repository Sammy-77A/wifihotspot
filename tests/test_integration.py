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
from app import app, CONFIG, cyzora_client, ADMIN_USERNAME, ADMIN_PASSWORD


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

    # ------------------------------------------------------------------
    # 6. Voucher System & Edge Case Tests
    # ------------------------------------------------------------------
    def test_11_voucher_code_format(self):
        code = database.generate_voucher_code()
        self.assertTrue(code.startswith("LUMO-"))
        self.assertEqual(len(code), 11)  # LUMO- (5) + 6 chars
        suffix = code.split("-", 1)[1]
        for char in suffix:
            self.assertIn(char, database.VOUCHER_CHARSET)
            self.assertNotIn(char, ("0", "O", "1", "I"))

    def test_12_voucher_batch_creation(self):
        batch = database.create_vouchers(
            plan_id="1hr",
            plan_name="1 Hour Pass",
            duration_seconds=3600,
            amount_kes=10,
            quantity=5,
        )
        self.assertEqual(len(batch), 5)
        codes = [v["code"] for v in batch]
        self.assertEqual(len(set(codes)), 5)  # All codes unique

        for v in batch:
            stored = database.get_voucher(v["code"])
            self.assertIsNotNone(stored)
            self.assertEqual(stored["status"], "unused")
            self.assertEqual(stored["plan_id"], "1hr")

    def test_13_api_redeem_voucher_valid(self):
        batch = database.create_vouchers(
            plan_id="3min",
            plan_name="3 Minutes Test Pass",
            duration_seconds=180,
            amount_kes=1,
            quantity=1,
        )
        code = batch[0]["code"]

        resp = self.client.post("/api/redeem-voucher", json={
            "code": code,
            "mac": "12:34:56:78:9A:BC",
            "ip": "192.168.5.105",
            "gateway_url": "http://192.168.5.1/",
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])
        self.assertTrue(data["access_granted"])
        self.assertEqual(data["status"], "succeeded")
        self.assertIn("session_id", data)
        self.assertEqual(data["customer_voucher"], code)

        # Check voucher in DB is now redeemed
        stored = database.get_voucher(code)
        self.assertEqual(stored["status"], "redeemed")
        self.assertEqual(stored["redeemed_by_mac"], "12:34:56:78:9A:BC")

    def test_13b_api_redeem_voucher_without_explicit_ip_or_mac(self):
        # Simulates real phone sending only {"code": "...", "gateway_url": "..."}
        batch = database.create_vouchers(
            plan_id="1hr",
            plan_name="1 Hour Pass",
            duration_seconds=3600,
            amount_kes=10,
            quantity=1,
        )
        code = batch[0]["code"]

        resp = self.client.post("/api/redeem-voucher", json={
            "code": code,
            "gateway_url": "http://192.168.5.1/",
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])
        self.assertTrue(data["access_granted"])
        self.assertEqual(data["customer_voucher"], code)

    def test_14_api_redeem_voucher_already_used(self):
        batch = database.create_vouchers(
            plan_id="1hr",
            plan_name="1 Hour Pass",
            duration_seconds=3600,
            amount_kes=10,
            quantity=1,
        )
        code = batch[0]["code"]

        # First redemption
        resp1 = self.client.post("/api/redeem-voucher", json={
            "code": code,
            "mac": "AA:BB:CC:DD:EE:01",
            "ip": "192.168.5.101",
        })
        self.assertEqual(resp1.status_code, 200)

        # Second redemption with same code -> must fail
        resp2 = self.client.post("/api/redeem-voucher", json={
            "code": code,
            "mac": "AA:BB:CC:DD:EE:02",
            "ip": "192.168.5.102",
        })
        self.assertEqual(resp2.status_code, 400)
        data2 = json.loads(resp2.data)
        self.assertFalse(data2["success"])
        self.assertEqual(data2["error"], "This voucher has already been used")

    def test_15_api_redeem_voucher_invalid_code(self):
        resp = self.client.post("/api/redeem-voucher", json={
            "code": "LUMO-NONEXISTENT",
            "mac": "AA:BB:CC:DD:EE:03",
            "ip": "192.168.5.103",
        })
        self.assertEqual(resp.status_code, 404)
        data = json.loads(resp.data)
        self.assertFalse(data["success"])
        self.assertEqual(data["error"], "Invalid voucher code")

    def test_16_api_redeem_voucher_expired(self):
        batch = database.create_vouchers(
            plan_id="1hr",
            plan_name="1 Hour Pass",
            duration_seconds=3600,
            amount_kes=10,
            quantity=1,
        )
        code = batch[0]["code"]

        # Manually backdate expires_at to the past
        conn = database.get_db_connection()
        conn.execute(
            "UPDATE vouchers SET expires_at = '2020-01-01T00:00:00+00:00' WHERE code = ?",
            (code,),
        )
        conn.commit()
        conn.close()

        resp = self.client.post("/api/redeem-voucher", json={
            "code": code,
            "mac": "AA:BB:CC:DD:EE:04",
            "ip": "192.168.5.104",
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data)
        self.assertFalse(data["success"])
        self.assertEqual(data["error"], "This voucher has expired")

    # ------------------------------------------------------------------
    # 7. Admin Panel & Authentication Tests
    # ------------------------------------------------------------------
    def test_17_admin_auth_flow(self):
        # 1. Unauthenticated request to /admin redirects to /admin/login
        resp_unauth = self.client.get("/admin")
        self.assertEqual(resp_unauth.status_code, 302)
        self.assertIn("/admin/login", resp_unauth.headers.get("Location", ""))

        # 2. Invalid credentials fail
        resp_fail = self.client.post("/admin/login", data={"username": ADMIN_USERNAME, "password": "wrongpassword123"})
        self.assertEqual(resp_fail.status_code, 200)
        self.assertIn(b"Invalid username or password", resp_fail.data)

        # 3. Valid credentials succeed
        resp_login = self.client.post("/admin/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}, follow_redirects=True)
        self.assertEqual(resp_login.status_code, 200)
        self.assertIn(b"Voucher Generator", resp_login.data)

        # 4. Logout clears session
        resp_logout = self.client.get("/admin/logout", follow_redirects=True)
        self.assertEqual(resp_logout.status_code, 200)
        self.assertIn(b"Hotspot Admin", resp_logout.data)

    def test_18_admin_voucher_generate_and_export(self):
        # Login first
        self.client.post("/admin/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

        # Generate batch of 3 vouchers via JSON
        resp_gen = self.client.post(
            "/admin/vouchers/generate",
            json={"plan_id": "1hr", "quantity": 3},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        self.assertEqual(resp_gen.status_code, 200)
        data = json.loads(resp_gen.data)
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 3)

        # Download CSV export
        resp_csv = self.client.get("/admin/vouchers/export.csv")
        self.assertEqual(resp_csv.status_code, 200)
        self.assertIn("text/csv", resp_csv.headers.get("Content-Type", ""))
        self.assertIn(b"Voucher Code,Plan ID,Plan Name", resp_csv.data)

    def test_19_admin_session_manual_revoke(self):
        # Create an active session
        sess_id = "TEST-ADMIN-REVOKE-01"
        database.create_active_voucher_session(
            session_id=sess_id,
            client_ip="192.168.5.199",
            client_mac="FE:DC:BA:98:76:54",
            plan_id="1hr",
            plan_name="1 Hour Pass",
            amount_kes=10,
            duration_seconds=3600,
            voucher_code="LUMO-REVOKE1",
        )
        sess = database.get_session_by_id(sess_id)
        self.assertEqual(sess["status"], "active")

        # Admin revokes session
        self.client.post("/admin/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        resp_revoke = self.client.post(f"/admin/sessions/revoke/{sess_id}", headers={"Accept": "application/json"})
        self.assertEqual(resp_revoke.status_code, 200)

        # Verify session is now revoked/expired
        sess_after = database.get_session_by_id(sess_id)
        self.assertEqual(sess_after["status"], "expired")

    def test_20_voucher_prefix_optional(self):
        # Create vouchers to test prefix-optional redemption
        batch = database.create_vouchers(
            plan_id="1hr",
            plan_name="1 Hour Pass",
            duration_seconds=3600,
            amount_kes=10,
            quantity=2,
        )
        full_code_1 = batch[0]["code"]
        suffix_1 = full_code_1.split("-")[1]

        full_code_2 = batch[1]["code"]
        suffix_2 = full_code_2.split("-")[1]

        # 1. database.get_voucher matches suffix only
        v1 = database.get_voucher(suffix_1)
        self.assertIsNotNone(v1)
        self.assertEqual(v1["code"], full_code_1)

        # 2. database.get_voucher matches lowercase suffix
        v1_lower = database.get_voucher(suffix_1.lower())
        self.assertIsNotNone(v1_lower)
        self.assertEqual(v1_lower["code"], full_code_1)

        # 3. database.get_voucher matches unhyphenated "LUMO" + suffix
        v1_unhyphenated = database.get_voucher(f"lumo{suffix_1.lower()}")
        self.assertIsNotNone(v1_unhyphenated)
        self.assertEqual(v1_unhyphenated["code"], full_code_1)

        # 4. API redeem voucher using suffix only (e.g. 78X2KP)
        resp1 = self.client.post("/api/redeem-voucher", json={
            "code": suffix_1,
            "mac": "AA:BB:CC:DD:EE:77",
            "ip": "192.168.5.177",
        })
        self.assertEqual(resp1.status_code, 200)
        data1 = json.loads(resp1.data)
        self.assertTrue(data1["success"])
        self.assertTrue(data1["access_granted"])
        self.assertEqual(data1["customer_voucher"], full_code_1)

        # 5. API redeem voucher using unhyphenated lowercase (e.g. lumo78x2kp)
        resp2 = self.client.post("/api/redeem-voucher", json={
            "code": f"lumo{suffix_2.lower()}",
            "mac": "AA:BB:CC:DD:EE:88",
            "ip": "192.168.5.188",
        })
        self.assertEqual(resp2.status_code, 200)
        data2 = json.loads(resp2.data)
        self.assertTrue(data2["success"])
        self.assertTrue(data2["access_granted"])
        self.assertEqual(data2["customer_voucher"], full_code_2)


if __name__ == "__main__":
    unittest.main()

