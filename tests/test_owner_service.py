import io
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ledger_service import ENUM_GROUPS, LedgerClient
from owner_service import TianyanchaClient, archive_result
from business_scope_llm import ScopeAssessmentError
from test_ledger_service import record, record3

MAPPING = ENUM_GROUPS["customerCategories"]


def customer(label="风机厂", **updates):
    row = {"ID": 9000000000000000011, "field0010": "测试能源有限公司",
           "field0068": Decimal(next(key for key, item in MAPPING.items() if item["label"] == label))}
    row.update(updates)
    return row


class OwnerTests(unittest.TestCase):
    def test_archive_restricts_all_four_categories_and_preserves_exact_ids(self):
        for label, expected in (("风机厂", "风机厂"), ("综自客户", "综自厂家"),
                                ("代理商", "总包方"), ("关联方", "关联方")):
            with self.subTest(label=label):
                row = customer(label)
                report = archive_result(row["field0010"], [row], MAPPING)
                self.assertEqual(report["status"], "restricted")
                self.assertEqual(report["categories"], [expected])
                self.assertEqual(report["customerRecords"][0]["categoryId"], str(row["field0068"]))
                self.assertEqual(report["customerRecords"][0]["id"], str(row["ID"]))

    def test_other_labels_missing_and_conflicting_records(self):
        for label in ("不涉及", "竞争对手"):
            self.assertEqual(archive_result("业主", [customer(label)], MAPPING)["status"], "clear")
        for raw in (None, "", "1234567890123456789"):
            self.assertEqual(archive_result("业主", [customer(field0068=raw)], MAPPING)["status"], "review")
        self.assertEqual(archive_result("业主", [customer("不涉及"), customer("竞争对手")], MAPPING)["status"], "review")
        self.assertEqual(archive_result("业主", [customer("不涉及"), customer("关联方")], MAPPING)["status"], "restricted")

    def test_archive_precedes_external_and_is_parameterized(self):
        connection = MagicMock()
        cursor = connection
        owner = "测试能源'有限公司"
        cursor.execute.return_value.mappings.return_value.all.side_effect = [[record(field0009=owner)], [], [customer("代理商")]]
        external = MagicMock()
        report = LedgerClient(Path("unused"), engine=MagicMock(connect=MagicMock(return_value=connection)), tianyancha=external).review("P1")
        self.assertEqual(report["status"], "clear")  # Duplicate result remains separate.
        self.assertEqual(report["ownerReview"]["categories"], ["总包方"])
        query, parameters = cursor.execute.call_args.args
        query = str(query)
        self.assertIn("BINARY `field0010` = BINARY :owner", query)
        self.assertNotIn(owner, query)
        self.assertEqual(parameters, {"owner": owner})
        external.review.assert_not_called()

    def test_only_real_archive_miss_calls_external_after_connection_closes(self):
        for customer_rows, expected_external in (([], True), ([customer(field0068=None)], False)):
            connection = MagicMock()
            cursor = connection
            cursor.execute.return_value.mappings.return_value.all.side_effect = [[record(field0009="业主")], [], customer_rows]
            external = MagicMock()
            def external_review(owner):
                connection.close.assert_called_once()
                connection.rollback.assert_called_once()
                return {"status": "review", "ownerName": owner}
            external.review.side_effect = external_review
            LedgerClient(Path("unused"), engine=MagicMock(connect=MagicMock(return_value=connection)), tianyancha=external).review("P1")
            self.assertEqual(external.review.called, expected_external)

    def test_class3_and_unknown_category_never_query_customer_or_external(self):
        for target, batches, status in ((record3(field0009="业主"), 2, "skipped"),
                                         (record(field0026=None, field0009="业主"), 1, "review")):
            connection = MagicMock()
            cursor = connection
            cursor.execute.return_value.mappings.return_value.all.side_effect = [[target]] + [[]] * (batches - 1)
            external = MagicMock()
            report = LedgerClient(Path("unused"), engine=MagicMock(connect=MagicMock(return_value=connection)), tianyancha=external).review("P1")
            self.assertEqual(report["ownerReview"]["status"], status)
            self.assertFalse(any("formmain_4214" in str(call.args[0]) for call in cursor.execute.call_args_list))
            external.review.assert_not_called()

    def test_missing_plant_still_checks_owner_and_database_failure_is_not_a_miss(self):
        for rows in ([customer()], OSError("unavailable")):
            connection = MagicMock()
            cursor = connection
            cursor.execute.return_value.mappings.return_value.all.side_effect = [[record(field0024=None, field0009="业主")], rows]
            external = MagicMock()
            report = LedgerClient(Path("unused"), engine=MagicMock(connect=MagicMock(return_value=connection)), tianyancha=external).review("P1")
            self.assertEqual(report["status"], "review")
            self.assertEqual(report["ownerReview"]["status"], "review" if isinstance(rows, Exception) else "restricted")
            external.review.assert_not_called()

    def test_missing_owner_does_not_query_external(self):
        connection = MagicMock()
        cursor = connection
        cursor.execute.return_value.mappings.return_value.all.side_effect = [[record(field0009=" ")], []]
        external = MagicMock()
        report = LedgerClient(Path("unused"), engine=MagicMock(connect=MagicMock(return_value=connection)), tianyancha=external).review("P1")
        self.assertEqual(report["ownerReview"]["status"], "review")
        self.assertEqual(cursor.execute.call_count, 2)
        external.review.assert_not_called()


class TianyanchaTests(unittest.TestCase):
    def setUp(self):
        self.classifier = MagicMock(model="test-model")
        self.classifier.assess.return_value = self.assessments()

    def assessments(self, verdict="no"):
        return [{"category": category, "verdict": verdict if category == "总包方" else "no",
                 "reason": "模型判断依据", "evidence": ["工程总承包。"] if verdict == "yes" else []}
                for category in ("风机厂", "综自厂家", "总包方")]

    def response(self, payload):
        return io.BytesIO(json.dumps(payload, ensure_ascii=False).encode())

    def test_request_and_scope_inference(self):
        self.classifier.assess.return_value = self.assessments("yes")
        owner = "测试能源（中国）有限公司"
        opener = MagicMock(return_value=self.response({"error_code": 0, "result": {"name": owner, "businessScope": "工程总承包。", "legalPersonName": "负责人", "regCapital": "100万元", "regStatus": "存续", "creditCode": "CODE123", "unrelatedField": "不应返回"}}))
        report = TianyanchaClient(classifier=self.classifier, token="test-only", opener=opener).review(owner)
        request = opener.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "test-only")
        self.assertEqual(urlsplit(request.full_url).path, "/services/open/ic/baseinfo/normal")
        self.assertEqual(parse_qs(urlsplit(request.full_url).query), {"keyword": [owner]})
        self.assertEqual(opener.call_args.kwargs["timeout"], 10)
        self.assertEqual(report["status"], "restricted")
        self.assertEqual(report["categories"], ["总包方"])
        self.assertTrue(report["inferred"])
        self.classifier.assess.assert_called_once_with(owner, "工程总承包。")
        self.assertEqual(report["classificationMethod"], "llm")
        self.assertEqual(report["model"], "test-model")
        self.assertEqual(report["companyInfo"], {"legalPersonName": "负责人", "regCapital": "100万元", "regStatus": "存续", "creditCode": "CODE123"})
        self.assertNotIn("test-only", json.dumps(report))

    def test_parenthesis_width_does_not_block_business_scope_review(self):
        names = ("华润风电(汕尾)有限公司", "华润风电（汕尾）有限公司")
        for owner, returned in (names, names[::-1]):
            for scope, expected in (("风力发电；风电场运营。", "clear"),
                                    ("工程总承包。", "restricted"), (None, "review")):
                with self.subTest(owner=owner, scope=scope):
                    opener = MagicMock(return_value=self.response({
                        "error_code": 0, "result": {"name": returned, "businessScope": scope}}))
                    self.classifier.assess.return_value = self.assessments("yes" if expected == "restricted" else "no")
                    report = TianyanchaClient(classifier=self.classifier, token="test", opener=opener).review(owner)
                    self.assertEqual(report["status"], expected)
                    self.assertNotIn("企业名称与业主全称不一致", report["message"])
                    self.assertEqual(report["ownerName"], owner)
                    if scope:
                        self.assertEqual(report["matchedCompanyName"], returned)
                        self.assertEqual(report["businessScope"], scope)

    def test_meaningful_company_name_differences_still_require_review(self):
        owner = "华润风电(汕尾)有限公司"
        for returned in ("华润风电（汕头）有限公司", "华润风电有限公司",
                         "华润风电（汕尾）有限公司分公司"):
            with self.subTest(returned=returned):
                opener = MagicMock(return_value=self.response({
                    "error_code": 0, "result": {"name": returned, "businessScope": "风力发电。"}}))
                report = TianyanchaClient(classifier=self.classifier, token="test", opener=opener).review(owner)
                self.assertEqual(report["status"], "review")
                self.assertIn("企业名称与业主全称不一致", report["message"])

    def test_no_match_is_explicitly_an_inference_not_affiliate_check(self):
        opener = MagicMock(return_value=self.response({"error_code": "0", "result": {"name": "业主", "businessScope": "太阳能发电。"}}))
        report = TianyanchaClient(classifier=self.classifier, token="test", opener=opener).review("业主")
        self.assertEqual(report["status"], "clear")
        self.assertTrue(report["inferred"])
        self.assertIn("不判断关联方", report["limitation"])

    def test_llm_uncertainty_and_failure_are_not_clear(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                self.classifier.assess.return_value = self.assessments("uncertain")
                self.classifier.assess.side_effect = ScopeAssessmentError("LLM 请求失败") if failure else None
                opener = MagicMock(return_value=self.response({"error_code": 0, "result": {
                    "name": "业主", "businessScope": "综合服务。"}}))
                report = TianyanchaClient(classifier=self.classifier, token="test", opener=opener).review("业主")
                self.assertEqual(report["status"], "review")
                self.assertEqual(report["businessScope"], "综合服务。")
                self.assertEqual(report["classificationMethod"], "llm")

    def test_restriction_is_preserved_with_other_uncertain_categories(self):
        self.classifier.assess.return_value = self.assessments("yes")
        self.classifier.assess.return_value[0]["verdict"] = "uncertain"
        opener = MagicMock(return_value=self.response({"error_code": 0, "result": {
            "name": "业主", "businessScope": "工程总承包。"}}))
        report = TianyanchaClient(classifier=self.classifier, token="test", opener=opener).review("业主")
        self.assertEqual(report["status"], "restricted")
        self.assertEqual(report["categories"], ["总包方"])
        self.assertIn("仍待核实", report["message"])

    def test_unsuccessful_or_mismatched_data_never_clears(self):
        payloads = [{"error_code": code} for code in (300000, 300004, 300005, 300006)]
        payloads += [[], {}, {"error_code": 0, "result": []},
                     {"error_code": 0, "result": {"name": "另一家公司", "businessScope": "发电。"}},
                     {"error_code": 0, "result": {"name": "业主", "businessScope": None}}]
        for payload in payloads:
            with self.subTest(payload=payload):
                opener = MagicMock(return_value=self.response(payload))
                self.assertEqual(TianyanchaClient(classifier=self.classifier, token="test", opener=opener).review("业主")["status"], "review")
        for failure in (TimeoutError(), OSError(), ValueError()):
            opener = MagicMock(side_effect=failure)
            self.assertEqual(TianyanchaClient(classifier=self.classifier, token="test", opener=opener).review("业主")["status"], "review")
        opener = MagicMock()
        self.assertEqual(TianyanchaClient(opener=opener).review("业主")["status"], "review")
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
