import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ledger_service import (CLASS12_IDS, CLASS12_POLICY, CLASS3_IDS, CLASS3_POLICY,
                            ENUM_GROUPS, LedgerClient, compare_records, select_policy)


def record(**updates):
    result = {"ID": 1, "field0007": "P1", "field0008": "项目一", "field0024": "测试电厂",
              "field0013": 9000000000000000001, "field0014": 9000000000000000003,
              "field0015": -9000000000000000001,
              "field0026": next(iter(CLASS12_IDS)),
              "field0027": 9000000000000000002, "field0025": Decimal("0.630000")}
    result.update(updates)
    return result


def record3(**updates):
    result = record(ID=3, field0007="P3", field0008="三类项目", field0026=None,
                    field0036=next(iter(CLASS3_IDS)), field0033=-8778677584179871492,
                    field0035="测试省电力公司", field0034="调度中心", field0425="2025",
                    field0037=-6644091633990679371)
    result.update(updates)
    return result


class RuleTests(unittest.TestCase):
    def test_enum_names_preserve_original_ids_in_summary_and_comparison(self):
        target = record(field0013=-4350339289354188923, field0014=2149673691791443413,
                        field0015=-6365512568888474295, field0027=6471129809400053937)
        result = compare_records(target, [{**target, "ID": 2}])
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(result["target"]["province"], "-4350339289354188923")
        self.assertEqual(result["target"]["displayValues"], {
            "province": "广东", "city": "梅州市", "district": "平远县",
            "productSubclass": "光伏电站有功功率、无功功率自动控制系统V1.0"})
        city = next(d for d in result["candidates"][0]["dimensions"] if d["key"] == "city")
        self.assertEqual(city["targetValue"], "2149673691791443413")
        self.assertEqual((city["targetDisplayValue"], city["candidateDisplayValue"]), ("梅州市", "梅州市"))

    def test_equal_names_with_different_ids_are_still_different(self):
        with patch.dict(ENUM_GROUPS, {"regions": {"1": {"label": "同名地区"}, "2": {"label": "同名地区"}}}):
            result = compare_records(record(field0014=1), [record(ID=2, field0014=2)])
        self.assertEqual(result["status"], "clear")
        city = next(d for d in result["candidates"][0]["dimensions"] if d["key"] == "city")
        self.assertEqual(city["targetDisplayValue"], city["candidateDisplayValue"])
        self.assertEqual(city["status"], "different")

    def test_unmapped_ids_and_missing_values_are_distinct(self):
        result = compare_records(record(), [record(ID=2)])
        self.assertEqual(result["status"], "duplicate")
        self.assertIsNone(result["target"]["displayValues"]["city"])
        self.assertEqual(result["target"]["city"], "9000000000000000003")
        missing = compare_records(record(field0014=None), [record(ID=2)])
        self.assertEqual(missing["status"], "review")
        self.assertIsNone(missing["target"]["city"])

    def test_self_is_excluded(self):
        result = compare_records(record(), [record()])
        self.assertEqual((result["status"], result["checkedCount"]), ("clear", 0))

    def test_all_five_equal_and_other_id_is_duplicate(self):
        result = compare_records(record(), [record(ID=2, field0007="P2", field0025=Decimal(".63"))])
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(result["duplicateCount"], 1)
        self.assertEqual(result["target"]["province"], "9000000000000000001")
        self.assertEqual(result["target"]["city"], "9000000000000000003")

    def test_each_of_five_differences_rules_out_duplicate(self):
        for field in ("field0013", "field0014", "field0015", "field0027", "field0025"):
            with self.subTest(field=field):
                result = compare_records(record(), [record(ID=2, **{field: Decimal("1")})])
                self.assertEqual(result["status"], "clear")
                self.assertEqual(result["candidates"][0]["status"], "different")

    def test_product_line_and_class_three_subclass_do_not_affect_result(self):
        target = record(field0407=1, field0037=10)
        other = record(ID=2, field0407=2, field0037=20)
        result = compare_records(target, [other])
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(result["target"]["productSubclass"], "9000000000000000002")
        dimension = next(d for d in result["candidates"][0]["dimensions"] if d["key"] == "productSubclass")
        self.assertEqual((dimension["column"], dimension["status"]), ("field0027", "same"))

    def test_missing_city_prevents_duplicate(self):
        for target_city, other_city in ((None, None), (None, 1), (1, None), ("", "")):
            with self.subTest(target_city=target_city, other_city=other_city):
                result = compare_records(record(field0014=target_city), [record(ID=2, field0014=other_city)])
                self.assertEqual(result["status"], "review")
                self.assertEqual(result["duplicateCount"], 0)
                city = next(d for d in result["candidates"][0]["dimensions"] if d["key"] == "city")
                self.assertEqual((city["column"], city["status"]), ("field0014", "missing"))

    def test_missing_class_one_two_subclass_does_not_fall_back_to_other_fields(self):
        target = record(field0027=None, field0407=1, field0037=10)
        other = record(ID=2, field0027=None, field0407=1, field0037=10)
        result = compare_records(target, [other])
        self.assertEqual(result["status"], "review")
        self.assertIn("公司产品子类", result["missing"])
        self.assertEqual(result["duplicateCount"], 0)

    def test_different_plant_is_not_a_candidate(self):
        self.assertEqual(compare_records(record(), [record(ID=2, field0024="测试电厂二期")])["checkedCount"], 0)

    def test_missing_values_do_not_match(self):
        result = compare_records(record(field0025=None), [record(ID=2, field0025=None)])
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["duplicateCount"], 0)

    def test_missing_plant_requires_completion(self):
        self.assertEqual(compare_records(record(field0024="  "), [])["status"], "review")

    def test_missing_candidate_with_known_difference_does_not_block(self):
        result = compare_records(record(), [record(ID=2, field0013=2, field0025=None)])
        self.assertEqual(result["status"], "clear")

    def test_missing_candidate_without_known_difference_requires_review(self):
        self.assertEqual(compare_records(record(), [record(ID=2, field0025=None)])["status"], "review")

    def test_zero_capacity_is_not_missing(self):
        self.assertEqual(compare_records(record(field0025=Decimal(0)), [record(ID=2, field0025=Decimal("0.0"))])["status"], "duplicate")

    def test_unknown_and_ambiguous_project_do_not_query_candidates(self):
        for targets, expected in (([], "not_found"), ([record(), record(ID=2)], "ambiguous")):
            connection = MagicMock()
            cursor = connection
            cursor.execute.return_value.mappings.return_value.all.return_value = targets
            result = LedgerClient(Path("unused"), engine=MagicMock(connect=MagicMock(return_value=connection))).review("P1")
            self.assertEqual(result["status"], expected)
            self.assertEqual(cursor.execute.call_count, 1)
            connection.rollback.assert_called_once()
            connection.close.assert_called_once()

    def test_candidate_fetch_failure_is_not_a_clear_result(self):
        connection = MagicMock()
        cursor = connection
        cursor.execute.return_value.mappings.return_value.all.side_effect = [[record()], OSError("source unavailable")]
        with self.assertRaises(OSError):
            LedgerClient(Path("unused"), engine=MagicMock(connect=MagicMock(return_value=connection))).review("P1")
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()


class Class3RuleTests(unittest.TestCase):
    def test_rules_are_selected_by_explicit_category_ids(self):
        self.assertEqual(select_policy(record())[0]["id"], "class12")
        self.assertEqual(select_policy(record3())[0]["id"], "class3")
        for row in (record(field0026=None), record(field0026=123),
                    record3(field0026=next(iter(CLASS12_IDS))), record3(field0036=123)):
            with self.subTest(row=row):
                selected, reason = select_policy(row)
                self.assertIsNone(selected)
                self.assertTrue(reason)

    def test_six_equal_fields_are_duplicate_and_product_name_is_resolved(self):
        result = compare_records(record3(), [record3(ID=4)], CLASS3_POLICY)
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(len(result["candidates"][0]["dimensions"]), 6)
        self.assertEqual(result["target"]["displayValues"]["productClass"], "三类")
        self.assertEqual(result["target"]["displayValues"]["product"], "电网科技项目")
        self.assertEqual(result["target"]["grid"], "-8778677584179871492")

    def test_each_class3_difference_excludes_duplication(self):
        for field in ("field0033", "field0035", "field0034", "field0425", "field0036", "field0037"):
            with self.subTest(field=field):
                result = compare_records(record3(), [record3(ID=4, **{field: "other"})], CLASS3_POLICY)
                self.assertEqual(result["status"], "clear")
                if field != "field0035":
                    self.assertEqual(result["candidates"][0]["status"], "different")
                else:
                    self.assertEqual(result["checkedCount"], 0)

    def test_each_missing_class3_field_requires_review(self):
        for field in ("field0033", "field0035", "field0034", "field0425", "field0036", "field0037"):
            with self.subTest(field=field):
                result = compare_records(record3(**{field: None}), [record3(ID=4)], CLASS3_POLICY)
                self.assertEqual(result["status"], "review")
                self.assertEqual(result["duplicateCount"], 0)

    def test_candidate_missing_year_is_not_filled_from_department_or_name(self):
        target = record3(field0034="调度中心2025年")
        other = record3(ID=4, field0034="调度中心2025年", field0425=None,
                        field0008="国网测试省电力公司调度中心2025年三类电网科技项目")
        result = compare_records(target, [other], CLASS3_POLICY)
        self.assertEqual(result["status"], "review")
        year = next(d for d in result["candidates"][0]["dimensions"] if d["key"] == "year")
        self.assertEqual(year["status"], "missing")
        self.assertIsNone(year["candidateValue"])

    def test_plant_region_capacity_and_class12_product_do_not_affect_class3(self):
        target = record3(field0024=None, field0013=None, field0014=None, field0015=None,
                         field0025=None, field0027=None)
        result = compare_records(target, [record3(ID=4)], CLASS3_POLICY)
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(result["missing"], [])

    def test_opposite_category_is_excluded_for_both_rules(self):
        first = record(field0035="测试省电力公司")
        third = record3()
        self.assertEqual(compare_records(first, [third])["checkedCount"], 0)
        self.assertEqual(compare_records(third, [first], CLASS3_POLICY)["checkedCount"], 0)

    def test_ambiguous_candidate_category_cannot_be_marked_duplicate(self):
        result = compare_records(record3(), [record3(ID=4, field0026=next(iter(CLASS12_IDS)))], CLASS3_POLICY)
        self.assertEqual(result["status"], "review")
        self.assertTrue(result["candidates"][0]["issue"])

    def test_self_is_excluded_for_class3(self):
        self.assertEqual(compare_records(record3(), [record3()], CLASS3_POLICY)["checkedCount"], 0)

    def test_client_uses_matching_lookup_column_and_parameterized_value(self):
        for target, column, value in ((record(), "field0024", "测试电厂"),
                                      (record3(), "field0035", "测试省电力公司")):
            with self.subTest(column=column):
                connection = MagicMock()
                cursor = connection
                cursor.execute.return_value.mappings.return_value.all.side_effect = [[target], []]
                result = LedgerClient(Path("unused"), engine=MagicMock(connect=MagicMock(return_value=connection))).review(target["field0007"])
                query, params = cursor.execute.call_args.args
                query = str(query)
                self.assertIn(f"BINARY `{column}` = BINARY :lookup", query)
                self.assertEqual(params, {"lookup": value, "id": target["ID"]})
                self.assertEqual(result["policy"]["id"], select_policy(target)[0]["id"])
                connection.rollback.assert_called_once()
                connection.close.assert_called_once()

    def test_unclassified_target_needs_review_without_querying_candidates(self):
        connection = MagicMock()
        cursor = connection
        cursor.execute.return_value.mappings.return_value.all.return_value = [record3(field0026=next(iter(CLASS12_IDS)))]
        result = LedgerClient(Path("unused"), engine=MagicMock(connect=MagicMock(return_value=connection))).review("P3")
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["policy"]["id"], "unclassified")
        self.assertIn("同时有值", result["reviewReason"])
        self.assertEqual(cursor.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
