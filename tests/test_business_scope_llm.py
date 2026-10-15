import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from langchain_openai import ChatOpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from business_scope_llm import BusinessScopeLLM, CATEGORIES, ScopeAssessmentError


class BusinessScopeLLMTests(unittest.TestCase):
    scope = "风力发电机组制造；工程总承包。"

    def payload(self):
        return {"assessments": [
            {"category": category, "verdict": "no" if category == "综自厂家" else "yes",
             "reason": "依据经营范围判断", "evidence": [self.scope]}
            for category in CATEGORIES]}

    def client(self, content=None, finish="stop", failure=None, raw=None):
        def respond(request):
            self.request = request
            if failure:
                raise failure
            if raw is not None:
                return httpx.Response(200, content=raw)
            return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1,
                "model": "test-model", "choices": [{"index": 0, "finish_reason": finish,
                    "message": {"role": "assistant", "content": content}}]})
        http = httpx.Client(transport=httpx.MockTransport(respond))
        self.addCleanup(http.close)
        model = ChatOpenAI(base_url="http://example.test/openai/v1", api_key="test-secret",
                           model="test-model", http_client=http, max_retries=0,
                           timeout=60, use_responses_api=False, http_socket_options=())
        return BusinessScopeLLM("http://example.test/openai/v1/", "test-secret", "test-model", model)

    def test_langchain_request_contains_only_name_and_scope(self):
        assessments = self.client(json.dumps(self.payload())).assess("测试企业", self.scope)
        body = json.loads(self.request.content)
        self.assertEqual(str(self.request.url), "http://example.test/openai/v1/chat/completions")
        self.assertEqual(self.request.headers["Authorization"], "Bearer test-secret")
        self.assertEqual(body["model"], "test-model")
        self.assertFalse(body["stream"])
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(json.loads(body["messages"][1]["content"]),
                         {"companyName": "测试企业", "businessScope": self.scope})
        self.assertEqual([a["category"] for a in assessments], list(CATEGORIES))
        self.assertNotIn("test-secret", json.dumps(assessments))

    def test_invalid_classification_or_invented_evidence_fails_closed(self):
        payloads = [None, [], {}, {"assessments": []}]
        for key, value in (("category", "关联方"), ("category", ["风机厂"]),
                           ("verdict", "maybe"), ("reason", ""), ("evidence", []),
                           ("evidence", ["捏造的经营范围"]), ("evidence", [None]),
                           ("evidence", "工程总承包。")):
            payload = self.payload()
            payload["assessments"][0][key] = value
            payloads.append(payload)
        duplicate = self.payload()
        duplicate["assessments"][1] = copy.deepcopy(duplicate["assessments"][0])
        payloads.append(duplicate)
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(ScopeAssessmentError):
                self.client(json.dumps(payload)).assess("业主", self.scope)

    def test_uncertain_allows_empty_evidence(self):
        payload = self.payload()
        payload["assessments"][0].update(verdict="uncertain", evidence=[])
        self.assertEqual(self.client(json.dumps(payload)).assess("业主", self.scope)[0]["verdict"], "uncertain")

    def test_transport_errors_truncation_and_non_json_never_become_clear(self):
        for failure in (httpx.ReadTimeout("test-secret"), OSError("test-secret")):
            with self.assertRaises(ScopeAssessmentError) as caught:
                self.client(failure=failure).assess("业主", self.scope)
            self.assertNotIn("test-secret", str(caught.exception))
        for options in ({"content": "not JSON"}, {"content": json.dumps(self.payload()), "finish": "length"},
                        {"raw": b'{}'}, {"raw": b'null'}, {"raw": b'not JSON'}):
            with self.assertRaises(ScopeAssessmentError):
                self.client(**options).assess("业主", self.scope)

    def test_unconfigured_client_does_not_create_model(self):
        with patch("business_scope_llm.ChatOpenAI") as model, self.assertRaises(ScopeAssessmentError):
            BusinessScopeLLM().assess("业主", self.scope)
        model.assert_not_called()

    def test_environment_overrides_local_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "llm.json"
            path.write_text(json.dumps({"baseUrl": "http://file", "apiKey": "file-key", "model": "file-model"}))
            with patch.dict(os.environ, {"LLM_BASE_URL": "http://env", "LLM_API_KEY": "env-key", "LLM_MODEL": "env-model"}):
                client = BusinessScopeLLM.from_settings(path)
            self.assertEqual((client.base_url, client.api_key, client.model), ("http://env", "env-key", "env-model"))
