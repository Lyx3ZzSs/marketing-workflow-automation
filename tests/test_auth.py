import io
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from auth import AuthSettings, TokenVerifier
from server import create_app

SETTINGS = AuthSettings("https://identity.example/realms/test", "https://identity.example/certs", "marketing-workflow-automation-api")


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.ledger = MagicMock()
        self.ledger.review.return_value = {"status": "clear"}
        self.app = create_app(lambda: self.ledger)
        self.app.state.token_verifier = TokenVerifier(SETTINGS)
        patcher = patch("jwt.jwks_client.urllib.request.build_opener")
        self.jwks = patcher.start().return_value.open
        self.addCleanup(patcher.stop)
        self.jwks.side_effect = lambda *a, **k: io.BytesIO(json.dumps(self.key_set(self.key, "current")).encode())
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def key_set(self, key, kid):
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
        return {"keys": [{**jwk, "kid": kid, "alg": "RS256", "use": "sig"}]}

    def claims(self, **changes):
        now = int(time.time())
        return {"iss": SETTINGS.issuer, "aud": SETTINGS.audience, "sub": "stable-user-id",
                "iat": now, "exp": now + 300, "typ": "Bearer", "preferred_username": "alice",
                "name": "测试用户", "email": "alice@example.com", "department_code": "RD",
                "department_name": "研发中心", "resource_access": {SETTINGS.audience: {"roles": ["agent_user"]}},
                **changes}

    def headers(self, claims=None, key=None, kid="current"):
        token = jwt.encode(claims if claims is not None else self.claims(), key or self.key,
                           algorithm="RS256", headers={"kid": kid})
        return {"Authorization": "Bearer " + token}

    def test_every_api_requires_authentication_and_does_not_query_data(self):
        for path in ("/api/me", "/api/health", "/api/policy"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["www-authenticate"], "Bearer")
            self.assertEqual(response.headers["cache-control"], "no-store")
        response = self.client.post("/api/project-reviews", json={"projectCode": "P1"})
        self.assertEqual(response.status_code, 401)
        self.ledger.review.assert_not_called()
        self.jwks.assert_not_called()

    def test_all_default_roles_can_access_and_claims_are_mapped(self):
        for role in ("agent_admin", "agent_manager", "agent_user"):
            headers = self.headers(self.claims(resource_access={SETTINGS.audience: {"roles": [role]}}))
            response = self.client.get("/api/me", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"user_id": "stable-user-id", "username": "alice",
                "display_name": "测试用户", "email": "alice@example.com", "department_code": "RD",
                "department_name": "研发中心", "roles": [role]})
            self.assertEqual(self.client.get("/api/policy", headers=headers).status_code, 200)
            self.assertEqual(self.client.post("/api/project-reviews", headers=headers, json={"projectCode": "P1"}).status_code, 200)
        self.assertEqual(self.jwks.call_count, 1, "JWKS must be cached between requests")

    def test_invalid_claims_signatures_and_token_types_are_rejected(self):
        now = int(time.time())
        cases = [{"exp": now - 1}, {"nbf": now + 300}, {"iat": now + 300},
                 {"iss": "https://other.example"}, {"aud": "other-api"}, {"sub": ""},
                 {"sub": 123}, {"typ": "ID"}]
        for changes in cases:
            with self.subTest(changes=changes):
                response = self.client.get("/api/me", headers=self.headers(self.claims(**changes)))
                self.assertEqual(response.status_code, 401, response.text)
        for field in ("exp", "iat", "iss", "aud", "sub"):
            claims = self.claims()
            del claims[field]
            self.assertEqual(self.client.get("/api/me", headers=self.headers(claims)).status_code, 401)
        self.assertEqual(self.client.get("/api/me", headers=self.headers(key=self.other_key)).status_code, 401)
        self.assertEqual(self.client.get("/api/me", headers=self.headers(kid="unknown")).status_code, 401)
        for token in ("garbage", jwt.encode(self.claims(), "test-key-at-least-thirty-two-bytes", algorithm="HS256", headers={"kid": "current"})):
            self.assertEqual(self.client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code, 401)

    def test_only_roles_from_the_api_client_grant_access(self):
        cases = [{}, {"other-api": {"roles": ["agent_admin"]}},
                 {SETTINGS.audience: {"roles": ["unknown"]}}, {SETTINGS.audience: {"roles": "agent_admin"}},
                 {SETTINGS.audience: {"roles": [None, {}]}}, {SETTINGS.audience: []}, None]
        for resources in cases:
            claims = self.claims(resource_access=resources, realm_access={"roles": ["agent_admin"]})
            response = self.client.post("/api/project-reviews", headers=self.headers(claims), json={"projectCode": "P1"})
            self.assertEqual(response.status_code, 403, response.text)
        self.ledger.review.assert_not_called()

    def test_audience_array_and_key_rotation(self):
        self.assertEqual(self.client.get("/api/me", headers=self.headers(self.claims(aud=["account", SETTINGS.audience]))).status_code, 200)
        self.jwks.side_effect = lambda *a, **k: io.BytesIO(json.dumps(self.key_set(self.other_key, "rotated")).encode())
        with patch("jwt.jwks_client.time", wraps=time) as clock:
            clock.monotonic.return_value = time.monotonic() + 31
            self.assertEqual(self.client.get("/api/me", headers=self.headers(key=self.other_key, kid="rotated")).status_code, 200)
        self.assertEqual(self.jwks.call_count, 2)

    def test_jwks_failure_fails_closed_without_leaking_details(self):
        self.jwks.side_effect = URLError("private-network-detail")
        response = self.client.post("/api/project-reviews", headers=self.headers(), json={"projectCode": "P1"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-network-detail", response.text)
        self.ledger.review.assert_not_called()

    def test_empty_jwks_reports_auth_service_failure(self):
        self.jwks.side_effect = lambda *a, **k: io.BytesIO(b'{"keys": []}')
        response = self.client.get("/api/me", headers=self.headers())
        self.assertEqual(response.status_code, 503)
