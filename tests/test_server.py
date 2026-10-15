from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from server import create_app
from auth import require_user


def authorized_app(factory):
    app = create_app(factory)
    app.dependency_overrides[require_user] = lambda: {"user_id": "test-user", "roles": ["agent_user"]}
    return app


class APITests(unittest.TestCase):
    def setUp(self):
        self.ledger = MagicMock()
        self.client = TestClient(authorized_app(lambda: self.ledger), raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_health_rules_and_documented_api(self):
        self.assertEqual(self.client.get("/api/health").json()["status"], "ready")
        response = self.client.get("/api/policy")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(len(response.json()["policies"]), 2)
        self.assertIn("stationPolicy", response.json())
        self.assertIn("/api/project-reviews", self.client.get("/openapi.json").json()["paths"])

    def test_review_preserves_contract_and_trims_code(self):
        for status, expected in (("clear", 200), ("not_found", 404), ("ambiguous", 409)):
            self.ledger.review.return_value = {"status": status, "code": "P1"}
            response = self.client.post("/api/project-reviews", json={"projectCode": " P1 "})
            self.assertEqual(response.status_code, expected)
            self.assertEqual(response.json()["status"], status)
            self.ledger.review.assert_called_with("P1")

    def test_invalid_input_never_reaches_database(self):
        for body in ({}, {"projectCode": None}, {"projectCode": 123}, {"projectCode": " "},
                     {"projectCode": "x" * 256}, [], "P1"):
            response = self.client.post("/api/project-reviews", json=body)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post("/api/project-reviews", content="{", headers={"Content-Type": "application/json"}).status_code, 400)
        self.assertEqual(self.client.post("/api/project-reviews", content="x" * 4097, headers={"Content-Type": "application/json"}).status_code, 400)
        self.assertEqual(self.client.post("/api/project-reviews", content="P1").status_code, 415)
        self.ledger.review.assert_not_called()

    def test_same_origin_next_proxy_and_cross_origin(self):
        self.ledger.review.return_value = {"status": "clear"}
        headers = {"Origin": "http://127.0.0.1:4186", "X-Forwarded-Host": "127.0.0.1:4186", "X-Forwarded-Proto": "http"}
        self.assertEqual(self.client.post("/api/project-reviews", json={"projectCode": "P1"}, headers=headers).status_code, 200)
        headers["Origin"] = "https://other.example"
        self.assertEqual(self.client.post("/api/project-reviews", json={"projectCode": "P1"}, headers=headers).status_code, 403)

    def test_failures_do_not_leak_provider_details(self):
        for error, status in ((OperationalError("secret-sql", {}, Exception("secret-password")), 503),
                              (OSError("secret-password"), 503), (ValueError("secret-password"), 500)):
            self.ledger.review.side_effect = error
            response = self.client.post("/api/project-reviews", json={"projectCode": "P1"})
            self.assertEqual(response.status_code, status)
            self.assertIn("未完成", response.json()["message"])
            self.assertNotIn("secret", response.text)

    def test_unconfigured_and_shutdown(self):
        with TestClient(authorized_app(lambda: None)) as client:
            self.assertEqual(client.get("/api/health").json()["status"], "unconfigured")
            self.assertEqual(client.post("/api/project-reviews", json={"projectCode": "P1"}).status_code, 503)
        ledger = MagicMock()
        with TestClient(authorized_app(lambda: ledger)):
            pass
        ledger.close.assert_called_once()
