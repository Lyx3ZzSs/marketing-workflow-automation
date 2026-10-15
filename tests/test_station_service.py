import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from station_service import query_station
from ledger_service import LedgerClient, SELECT_COLUMNS
from test_ledger_service import record, record3

# Synthetic IDs only; these must never be used as production option mappings.
MAPPING = {
    "field0020": {"11": "周期服务", "12": "其他产品"},
    "field0022": {"21": "服务项目", "22": "其他项目"},
    "field0404": {"31": "是", "32": "否"},
    "field0185": {"41": "服务", "42": "改造", "43": "新签"},
}


def target(**updates):
    return record(**{"field0020": 12, "field0022": 22, "field0404": 32,
                     "field0185": 43, **updates})


def candidate(**updates):
    return record(**{"ID": 2, "field0007": "P2", "field0008": "测试电厂", **updates})


class StationTests(unittest.TestCase):
    def review(self, row, candidates=()):
        cursor = MagicMock()
        cursor.execute.return_value.mappings.return_value.all.return_value = list(candidates)
        return query_station(cursor, row, MAPPING), cursor

    def test_service_and_retrofit_expected_values_and_mismatches(self):
        for changes, expected, correct in (({"field0020": 11, "field0022": 21}, "服务", 41),
                                            ({"field0404": 31}, "改造", 42)):
            for actual in (41, 42, 43):
                with self.subTest(expected=expected, actual=actual):
                    report, _ = self.review(target(**changes, field0185=actual))
                    self.assertEqual(report["expected"], expected)
                    self.assertEqual(report["status"], "clear" if actual == correct else "warning")

    def test_service_requires_both_conditions(self):
        for changes in ({"field0020": 11}, {"field0022": 21}):
            report, _ = self.review(target(**changes))
            self.assertIsNone(report["expected"])
            self.assertEqual(report["status"], "clear")

    def test_conflicting_conditions_require_review(self):
        for actual in (41, 42, 43):
            report, _ = self.review(target(field0020=11, field0022=21, field0404=31, field0185=actual))
            self.assertEqual(report["status"], "review")
            self.assertTrue(any("冲突" in c["message"] for c in report["checks"]))

    def test_new_signing_uses_project_name_and_subclass_only(self):
        other = candidate(field0024="另一电厂", field0013=0, field0014=0, field0025=99, field0026=None)
        report, cursor = self.review(target(), [other])
        self.assertEqual(report["status"], "warning")
        self.assertEqual(report["matches"][0]["code"], "P2")
        self.assertEqual(report["matches"][0]["productSubclass"], "9000000000000000002")
        sql, params = cursor.execute.call_args.args
        sql = str(sql)
        self.assertIn("BINARY `field0008` = BINARY :plant", sql)
        self.assertIn("`ID` <> :id", sql)
        self.assertNotIn("LIMIT", sql)
        self.assertEqual(params, {"plant": "测试电厂", "id": 1})

    def test_new_signing_excludes_self_other_names_and_different_subclasses(self):
        report, _ = self.review(target(), [candidate(ID=1), candidate(field0008="不同电厂"),
                                          candidate(field0027=9000000000000000003)])
        self.assertEqual(report["status"], "clear")
        self.assertEqual(report["matches"], [])
        self.assertEqual(report["checkedCount"], 1)

    def test_literal_name_is_parameterized(self):
        plant = "电厂%_\\'名称"
        report, cursor = self.review(target(field0024=plant), [candidate(field0008=plant)])
        self.assertEqual(report["status"], "warning")
        sql, params = cursor.execute.call_args.args
        sql = str(sql)
        self.assertNotIn(plant, sql)
        self.assertEqual(params, {"plant": plant, "id": 1})

    def test_new_signing_requires_exact_name_not_contains_or_normalized_text(self):
        plant = "测试A电厂"
        for name in (plant + "一期工程", "前缀" + plant, " " + plant, plant + " ", "测试a电厂"):
            with self.subTest(name=name):
                report, _ = self.review(target(field0024=plant), [candidate(field0008=name)])
                self.assertEqual(report["status"], "clear")
                self.assertEqual(report["checkedCount"], 0)
                self.assertEqual(report["matches"], [])

    def test_missing_unknown_and_unconfigured_options_never_pass(self):
        for column in MAPPING:
            for value in (None, "", "999"):
                report, _ = self.review(target(**{column: value}))
                self.assertEqual(report["status"], "review")
        cursor = MagicMock()
        self.assertEqual(query_station(cursor, target(), {})["status"], "review")
        cursor.execute.assert_not_called()

    def test_missing_plant_or_subclass_skips_search(self):
        for column in ("field0024", "field0027"):
            report, cursor = self.review(target(**{column: None}))
            self.assertEqual(report["status"], "review")
            cursor.execute.assert_not_called()

    def test_missing_candidate_subclass_requires_review_even_with_a_match(self):
        for others, expected in (([candidate(field0027=None)], "review"),
                                  ([candidate(field0027=None), candidate(ID=3)], "warning")):
            report, _ = self.review(target(), others)
            self.assertEqual(report["status"], expected)
            self.assertTrue(any(c["status"] == "review" for c in report["checks"]))

    def test_query_failure_is_incomplete(self):
        for method in ("execute", "fetchall"):
            cursor = MagicMock()
            (cursor.execute if method == "execute" else cursor.execute.return_value.mappings.return_value.all).side_effect = OSError("unavailable")
            report = query_station(cursor, target(), MAPPING)
            self.assertEqual(report["status"], "review")
            self.assertTrue(any("检索失败" in c["message"] for c in report["checks"]))

    @patch("station_service.STATION_ENUMS", MAPPING)
    def test_integration_preserves_duplicate_result_and_snapshot(self):
        connection = MagicMock()
        cursor = connection
        cursor.execute.return_value.mappings.return_value.all.side_effect = [[target()], [candidate()], []]
        report = LedgerClient(Path("unused"), engine=MagicMock(connect=MagicMock(return_value=connection))).review("P1")
        self.assertEqual(report["status"], "clear")
        self.assertEqual(report["stationReview"]["status"], "warning")
        self.assertIn("CONSISTENT SNAPSHOT, READ ONLY", cursor.exec_driver_sql.call_args.args[0])
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()
        for column in MAPPING:
            self.assertIn(column, SELECT_COLUMNS)

    @patch("station_service.STATION_ENUMS", MAPPING)
    def test_category_unknown_or_class3_does_not_skip_station_checks(self):
        for row in (target(field0026=None), {**record3(), **{k: target()[k] for k in MAPPING}}):
            connection = MagicMock()
            cursor = connection
            cursor.execute.return_value.mappings.return_value.all.side_effect = [[row], [candidate()], []]
            report = LedgerClient(Path("unused"), engine=MagicMock(connect=MagicMock(return_value=connection))).review("P1")
            self.assertEqual(report["stationReview"]["status"], "warning")


if __name__ == "__main__":
    unittest.main()
