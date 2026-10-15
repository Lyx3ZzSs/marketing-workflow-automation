"""Read-only duplicate checks, selected by the ledger's product category."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database import create_ledger_engine

from verify_contract_ledger import json_value
from owner_service import TianyanchaClient, query_owner, result as owner_result
from station_service import STATION_FIELDS, query_station

RULE_VERSION = "分类立项查重、业主及场站类型校验 v7"
FIELDS = (
    {"key": "plant", "column": "field0024", "label": "电厂名称", "type": "text"},
    {"key": "province", "column": "field0013", "label": "项目所在省份", "type": "enum"},
    {"key": "city", "column": "field0014", "label": "项目所在市", "type": "enum"},
    {"key": "district", "column": "field0015", "label": "项目所在区/县", "type": "enum"},
    {"key": "productSubclass", "column": "field0027", "label": "公司产品子类", "type": "enum"},
    {"key": "capacity", "column": "field0025", "label": "装机容量MW", "type": "decimal"},
)
CHECK_FIELDS = FIELDS[1:]
CLASS3_FIELDS = (
    {"key": "grid", "column": "field0033", "label": "电网分类（国网/南网）", "type": "enum"},
    {"key": "company", "column": "field0035", "label": "分部/省/市电力公司", "type": "text"},
    {"key": "department", "column": "field0034", "label": "部门", "type": "text"},
    {"key": "year", "column": "field0425", "label": "年份", "type": "text"},
    {"key": "productClass", "column": "field0036", "label": "产品类别", "type": "enum"},
    {"key": "product", "column": "field0037", "label": "公司产品", "type": "enum"},
)
CLASSIFICATION_FIELDS = (
    {"key": "class12", "column": "field0026", "label": "一二类公司产品", "type": "enum"},
    {"key": "class3", "column": "field0036", "label": "三类公司产品", "type": "enum"},
)
CLASS12_POLICY = {
    "id": "class12", "name": "一二类产品", "version": "电厂及五项一致规则 v3",
    "fields": FIELDS, "checkFields": CHECK_FIELDS, "lookup": FIELDS[0],
    "candidateLabel": "同名电厂项目",
    "description": "电厂名称相同，省份、市、区县、公司产品子类和装机容量MW五项均有值且一致时，提示重复。",
    "scope": "全部同名电厂的一二类项目及类别待核实记录，不按项目状态过滤；排除当前记录",
}
CLASS3_POLICY = {
    "id": "class3", "name": "三类产品", "version": "三类六项一致规则 v1",
    "fields": CLASS3_FIELDS, "checkFields": CLASS3_FIELDS, "lookup": CLASS3_FIELDS[1],
    "candidateLabel": "同一电力公司项目",
    "description": "电网分类、电力公司、部门、年份、三类及公司产品六项均有值且一致时，提示重复。",
    "scope": "全部同一电力公司的三类项目及类别待核实记录，不按项目状态过滤；排除当前记录",
}
UNCLASSIFIED_POLICY = {
    "id": "unclassified", "name": "产品类别待核实", "version": RULE_VERSION,
    "fields": CLASSIFICATION_FIELDS, "checkFields": (), "lookup": None,
    "candidateLabel": "候选项目", "description": "先核实产品类别，再执行对应查重规则。",
    "scope": "产品类别尚未确定，未执行候选查询",
}
POLICIES = (CLASS12_POLICY, CLASS3_POLICY)
SELECT_COLUMNS = ", ".join(dict.fromkeys(["ID", "field0007", "field0008", "field0009"] +
                                        [f["column"] for f in FIELDS + CLASS3_FIELDS + CLASSIFICATION_FIELDS + STATION_FIELDS]))
ENUM_GROUPS = json.loads((Path(__file__).resolve().parents[1] / "config/contract_ledger_enums.json").read_text(encoding="utf-8"))["groups"]
FIELD_ENUM_GROUP = {"field0013": "regions", "field0014": "regions", "field0015": "regions",
                    "field0026": "products12", "field0027": "products12",
                    "field0036": "products3", "field0037": "products3"}
CLASS12_IDS = frozenset(key for key, entry in ENUM_GROUPS["products12"].items()
                       if entry["parentId"] == "0" and entry["label"] in ("一类", "二类"))
CLASS3_IDS = frozenset(key for key, entry in ENUM_GROUPS["products3"].items()
                      if entry["parentId"] == "0" and entry["label"] == "三类")


def enum_display_value(field, value):
    """Names only affect display; comparison continues to use the stored ID."""
    if field["type"] != "enum" or comparable(value, "enum") is None:
        return None
    group = FIELD_ENUM_GROUP.get(field["column"])
    return ENUM_GROUPS.get(group, {}).get(str(value), {}).get("label")


def comparable(value, kind):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if kind == "decimal":
        try:
            number = Decimal(str(value))
            return number if number.is_finite() else None
        except InvalidOperation:
            return None
    # Enum IDs remain exact strings, without JS Number precision loss.
    # Text is exact: no fuzzy matching, punctuation removal or plant aliases.
    return str(value)


def select_policy(row):
    first = comparable(row.get("field0026"), "enum")
    third = comparable(row.get("field0036"), "enum")
    if first is not None and third is not None:
        return None, "一二类和三类类别字段同时有值，请先核实项目类别。"
    if first in CLASS12_IDS and third is None:
        return CLASS12_POLICY, None
    if third in CLASS3_IDS and first is None:
        return CLASS3_POLICY, None
    return None, "产品类别缺失或无法识别，请先核实一二类、三类类别字段。"


def project_summary(row, policy=CLASS12_POLICY):
    values = {field["key"]: json_value(row.get(field["column"])) for field in policy["fields"]}
    display_values = {field["key"]: enum_display_value(field, row.get(field["column"]))
                      for field in policy["fields"] if field["type"] == "enum"}
    return {"id": str(row["ID"]), "code": row.get("field0007"),
            "name": row.get("field0008") or "未填写项目名称", **values, "displayValues": display_values}


def compare_records(target, other_records, policy=CLASS12_POLICY):
    """A known difference rules out duplication; missing or mixed categories need review."""
    missing = [field["label"] for field in policy["fields"]
               if comparable(target.get(field["column"]), field["type"]) is None]
    lookup = policy["lookup"]
    candidates = []
    for other in other_records:
        if str(other["ID"]) == str(target["ID"]):
            continue
        if comparable(target.get(lookup["column"]), lookup["type"]) is None:
            continue
        if other.get(lookup["column"]) != target.get(lookup["column"]):
            continue
        candidate_policy, classification_issue = select_policy(other)
        if candidate_policy is not None and candidate_policy["id"] != policy["id"]:
            continue
        dimensions = []
        for field in policy["checkFields"]:
            left = comparable(target.get(field["column"]), field["type"])
            right = comparable(other.get(field["column"]), field["type"])
            status = "missing" if left is None or right is None else "same" if left == right else "different"
            dimensions.append({**field, "status": status,
                               "targetValue": json_value(target.get(field["column"])),
                               "candidateValue": json_value(other.get(field["column"])),
                               "targetDisplayValue": enum_display_value(field, target.get(field["column"])),
                               "candidateDisplayValue": enum_display_value(field, other.get(field["column"]))})
        states = {dimension["status"] for dimension in dimensions}
        status = "different" if "different" in states else "review" if "missing" in states or classification_issue else "duplicate"
        candidates.append({"project": project_summary(other, policy), "status": status, "dimensions": dimensions,
                           "issue": classification_issue if status == "review" else None})
    priority = {"duplicate": 0, "review": 1, "different": 2}
    candidates.sort(key=lambda item: (priority[item["status"]], item["project"]["code"] or "", item["project"]["id"]))
    duplicates = sum(item["status"] == "duplicate" for item in candidates)
    uncertain = sum(item["status"] == "review" for item in candidates)
    status = "duplicate" if duplicates else "review" if missing or uncertain else "clear"
    return {"status": status, "target": project_summary(target, policy), "candidates": candidates,
            "missing": missing, "checkedCount": len(candidates), "duplicateCount": duplicates,
            "incompleteCount": uncertain, "policyVersion": policy["version"], "policy": policy,
            "source": "formmain_8861", "checkedAt": datetime.now(timezone.utc).isoformat(),
            "scope": policy["scope"]}


def unclassified_report(target, reason):
    return {"status": "review", "target": project_summary(target, UNCLASSIFIED_POLICY),
            "candidates": [], "missing": ["产品类别"], "checkedCount": 0, "duplicateCount": 0,
            "incompleteCount": 0, "policyVersion": RULE_VERSION, "policy": UNCLASSIFIED_POLICY,
            "reviewReason": reason, "source": "formmain_8861",
            "checkedAt": datetime.now(timezone.utc).isoformat(), "scope": UNCLASSIFIED_POLICY["scope"]}


class LedgerClient:
    def __init__(self, credentials_document: Path | None = None, engine=None, tianyancha=None):
        self.engine = engine if engine is not None else create_ledger_engine(credentials_document)
        self.tianyancha = tianyancha or TianyanchaClient()

    def close(self):
        self.engine.dispose()

    def review(self, project_code: str):
        connection = self.engine.connect()
        try:
            connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            targets = connection.execute(text(
                f"SELECT {SELECT_COLUMNS} FROM `formmain_8861` WHERE `field0007` = :code LIMIT 2"
            ), {"code": project_code}).mappings().all()
            if not targets:
                return {"status": "not_found", "code": project_code, "policyVersion": RULE_VERSION}
            if len(targets) > 1:
                return {"status": "ambiguous", "code": project_code, "policyVersion": RULE_VERSION}
            target = targets[0]
            station = query_station(connection, target)
            policy, reason = select_policy(target)
            if policy is None:
                report = unclassified_report(target, reason)
                report["stationReview"] = station
                report["ownerReview"] = owner_result("review", target.get("field0009"), "ledger",
                                                    "项目类别待核实，尚未执行业主校验。")
                return report
            lookup = policy["lookup"]
            if comparable(target.get(lookup["column"]), lookup["type"]) is None:
                report = compare_records(target, [], policy)
            else:
                # BINARY enforces exact text regardless of database collation.
                # No LIMIT: partial candidates must never produce a false clear.
                candidates = connection.execute(text(
                    f"SELECT {SELECT_COLUMNS} FROM `formmain_8861` "
                    f"WHERE BINARY `{lookup['column']}` = BINARY :lookup AND `ID` <> :id"
                ), {"lookup": target[lookup["column"]], "id": target["ID"]}).mappings().all()
                report = compare_records(target, candidates, policy)
            owner = target.get("field0009")
            report["stationReview"] = station
            if policy["id"] == "class3":
                report["ownerReview"] = owner_result("skipped", owner, "ledger", "三类项目不执行业主校验。")
            else:
                try:
                    report["ownerReview"] = query_owner(connection, owner, ENUM_GROUPS["customerCategories"])
                except (SQLAlchemyError, OSError):
                    report["ownerReview"] = owner_result("review", owner, "customer_archive",
                                                        "客户档案查询失败，业主类别待核实。")
        finally:
            try:
                connection.rollback()
            finally:
                connection.close()
        # Release the database snapshot before waiting on the external service.
        if report["ownerReview"] is None:
            report["ownerReview"] = self.tianyancha.review(owner)
        report["checkedAt"] = datetime.now(timezone.utc).isoformat()
        return report
