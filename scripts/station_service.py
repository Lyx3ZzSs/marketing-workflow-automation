"""Station classification checks, independent of category-specific duplicate checks."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

STATION_FIELDS = (
    {"column": "field0020", "label": "产品类型"},
    {"column": "field0022", "label": "项目类型"},
    {"column": "field0404", "label": "是否是改造品"},
    {"column": "field0185", "label": "场站类型分类"},
)
STATION_ENUMS = json.loads((Path(__file__).resolve().parents[1] /
                           "config/station_type_enums.json").read_text(encoding="utf-8"))["fields"]
STATION_POLICY = {
    "version": "场站类型分类校验 v2",
    "description": "周期服务且为服务项目时应填服务；是否是改造品为是时应填改造。两项同时满足时提示条件冲突，待核实。",
    "lookup": "已填新签时，以电厂名称与其他记录的项目名称作完全相同匹配，公司产品子类编号一致则提醒。",
    "scope": "不按项目状态、地区或容量过滤；按记录 ID 排除当前记录。公司产品子类使用 field0027。",
    "fields": STATION_FIELDS,
}


def raw_id(value):
    return None if value is None or not str(value).strip() else str(value)


def query_station(connection, target, mapping=None):
    mapping = STATION_ENUMS if mapping is None else mapping
    fields = [{**field, "value": raw_id(target.get(field["column"])),
               "displayValue": mapping.get(field["column"], {}).get(raw_id(target.get(field["column"]))) }
              for field in STATION_FIELDS]
    labels = {field["column"]: field["displayValue"] for field in fields}
    checks = []
    matches = []
    checked_count = 0

    def add(rule, status, message):
        checks.append({"rule": rule, "status": status, "message": message})

    unknown = [field["label"] for field in fields if field["displayValue"] is None]
    if unknown:
        add("data", "review", "以下字段未填写或选项编号尚未映射：" + "、".join(unknown) + "。")
    actual = labels["field0185"]
    if actual is not None and actual not in ("服务", "改造", "新签"):
        add("data", "review", "场站类型分类不属于服务、改造、新签，请核实选项映射。")

    # Three-valued logic: unknown options cannot establish a negative condition.
    service_parts = [None if labels[column] is None else labels[column] == expected
                     for column, expected in (("field0020", "周期服务"), ("field0022", "服务项目"))]
    service = False if False in service_parts else None if None in service_parts else True
    retrofit = None if labels["field0404"] is None else labels["field0404"] == "是"
    expected = None
    if service is True and retrofit is True:
        add("classification", "review", "同时满足周期服务＋服务项目和改造品＝是，分类条件冲突，请人工核实。")
    else:
        expected = "服务" if service is True else "改造" if retrofit is True else None
        if expected and actual in ("服务", "改造", "新签"):
            add("classification", "clear" if actual == expected else "warning",
                f"按当前项目条件，场站类型分类应为“{expected}”，当前为“{actual}”。")
        elif expected:
            add("classification", "review", f"按当前项目条件，场站类型分类应为“{expected}”，当前值待核实。")
        elif actual in ("服务", "改造"):
            add("classification", "review", f"当前分类为“{actual}”，但未确认命中服务或改造条件，请核实。")

    if actual == "新签":
        plant = target.get("field0024")
        subclass = raw_id(target.get("field0027"))
        if raw_id(plant) is None or subclass is None:
            add("new_signing", "review", "新签校验需要电厂名称和公司产品子类，当前资料缺失。")
        else:
            try:
                # BINARY enforces exact text, including case and trailing whitespace.
                rows = connection.execute(text(
                    "SELECT ID, field0007, field0008, field0027 FROM `formmain_8861` "
                    "WHERE BINARY `field0008` = BINARY :plant AND `ID` <> :id"
                ), {"plant": plant, "id": target["ID"]}).mappings().all()
            except (SQLAlchemyError, OSError):
                add("new_signing", "review", "新签项目名称检索失败，本项校验未完成。")
            else:
                incomplete = 0
                for row in rows:
                    if str(row["ID"]) == str(target["ID"]) or row.get("field0008") != plant:
                        continue
                    checked_count += 1
                    other_subclass = raw_id(row.get("field0027"))
                    if other_subclass is None:
                        incomplete += 1
                    elif other_subclass == subclass:
                        matches.append({"id": str(row["ID"]), "code": row.get("field0007"),
                                        "name": row.get("field0008"), "productSubclass": other_subclass})
                if matches:
                    add("new_signing", "warning", f"当前分类为“新签”，但找到 {len(matches)} 个项目名称与该电厂名称完全相同且公司产品子类相同的其他项目，请核实是否应为新签。")
                if incomplete:
                    add("new_signing", "review", f"检索到的 {incomplete} 个其他项目缺少公司产品子类，需进一步核实。")
                if not matches and not incomplete:
                    add("new_signing", "clear", "未发现项目名称与该电厂名称完全相同且公司产品子类相同的其他项目。")

    status = "warning" if any(c["status"] == "warning" for c in checks) else "review" if (
        not checks or any(c["status"] == "review" for c in checks)) else "clear"
    return {"status": status, "fields": fields, "expected": expected, "checks": checks,
            "matches": matches, "checkedCount": checked_count,
            "plant": target.get("field0024"), "productSubclass": raw_id(target.get("field0027")),
            "policyVersion": STATION_POLICY["version"]}
