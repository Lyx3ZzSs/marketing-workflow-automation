"""Read-only verification of a Seeyon contract ledger record.

Credentials are read into memory from the user-supplied document, never logged.
Run with: uv run --no-project --with pymysql scripts/verify_contract_ledger.py
  --credentials-doc /absolute/path/to/document.docx --project-code CODE
"""
from __future__ import annotations

import argparse
import base64
import datetime
import decimal
import json
import os
from pathlib import Path
import re
import time
from zipfile import ZipFile
from xml.etree import ElementTree

import pymysql


def label_records(rows: list[dict], field_map: dict, schema: list[dict]) -> list[list[dict]]:
    if field_map.get("table") != "formmain_8861":
        raise ValueError("字段映射不属于项目合同台账主表")
    definitions = {field["column"]: field for field in field_map["fields"]}
    if len(definitions) != len(field_map["fields"]):
        raise ValueError("字段映射包含重复编号")
    unknown = set(definitions) - {column["Field"] for column in schema}
    if unknown:
        raise ValueError(f"字段映射中有数据库不存在的字段：{sorted(unknown)}")
    result = []
    for row in rows:
        values = []
        for column, value in row.items():
            definition = definitions.get(column, {})
            input_type = definition.get("input_type")
            resolution = {
                "下拉": "枚举", "单选": "枚举", "图片下拉": "枚举",
                "选人": "人员", "选部门": "部门", "选岗位": "岗位", "上传附件": "附件",
            }.get(input_type)
            values.append({"column": column, "display_name": definition.get("display_name"),
                           "input_type": input_type, "raw_value": value,
                           "value_reference_type": resolution})
        result.append(values)
    return result


def read_credentials(document: Path) -> dict:
    with ZipFile(document) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = ["".join(p.itertext()) for p in root.findall(".//w:body//w:p", ns)]
    text = "\n".join(paragraphs)
    section = text.split("1.3创建数据库账号", 1)[1].split("2接口操作", 1)[0]

    def value(label: str) -> str:
        match = re.search(rf"(?m)^{re.escape(label)}[：:]\s*(.+)$", section)
        if not match:
            raise ValueError(f"接口说明缺少数据库配置项：{label}")
        return match.group(1).strip()

    return {"host": value("IP"), "database": value("数据库名称"),
            "user": value("账号"), "password": value("密码")}


def json_value(value):
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, int) and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-doc", required=True, type=Path)
    parser.add_argument("--project-code", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--field-map", type=Path,
                        default=Path(__file__).resolve().parent.parent / "config" / "contract_ledger_fields.json")
    args = parser.parse_args()
    field_map = json.loads(args.field_map.read_text(encoding="utf-8")) if args.field_map.is_file() else None
    credentials = read_credentials(args.credentials_doc)
    started = time.monotonic()
    connection = pymysql.connect(**credentials, port=3306, charset="utf8mb4",
                                 connect_timeout=8, read_timeout=20, write_timeout=10,
                                 cursorclass=pymysql.cursors.DictCursor, autocommit=False)
    try:
        with connection.cursor() as cursor:
            cursor.execute("START TRANSACTION READ ONLY")
            cursor.execute("SHOW FULL COLUMNS FROM `formmain_8861`")
            schema = cursor.fetchall()
            cursor.execute("SELECT * FROM `formmain_8861` WHERE `field0007` = %s LIMIT 2",
                           (args.project_code,))
            rows = cursor.fetchall()
            returned_columns = [field[0] for field in cursor.description]
            expected_columns = [field["Field"] for field in schema]
            if returned_columns != expected_columns:
                raise RuntimeError("返回字段与主表结构不一致")
            if any(row["field0007"] != args.project_code for row in rows):
                raise RuntimeError("查询返回的项目编号与输入不一致")
            summary = {
                "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "source": "mysql_read_only",
                "table": "formmain_8861",
                "project_code": args.project_code,
                "match_status": "unique" if len(rows) == 1 else "not_found" if not rows else "multiple",
                "returned_record_count": len(rows),
                "row_limit": 2,
                "schema_column_count": len(schema),
                "returned_column_count": len(returned_columns),
                "all_main_table_columns_returned": True,
                "non_null_columns_per_record": [sum(value is not None for value in row.values()) for row in rows],
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
            named_records = label_records(rows, field_map, schema) if field_map is not None else None
            if field_map is not None:
                summary["business_fields_with_display_names"] = len(field_map["fields"])
                summary["columns_without_display_names"] = [column for column in returned_columns
                                                              if column not in {field["column"] for field in field_map["fields"]}]
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                # Real data stays outside the static site and is ignored by Git.
                payload = {"verification": summary, "columns": schema, "records": rows}
                if named_records is not None:
                    payload["records_with_field_names"] = named_records
                data = json.dumps(json_value(payload),
                                  ensure_ascii=False, indent=2, allow_nan=False)
                descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                    file.write(data + "\n")
                os.chmod(args.output, 0o600)
                summary["local_output"] = str(args.output.resolve())
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if len(rows) == 1 else 2
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except pymysql.MySQLError as error:
        # Avoid logging connection credentials, queries or arbitrary server text.
        print(json.dumps({"error": "数据库查询失败", "mysql_error_code": error.args[0] if error.args else None},
                         ensure_ascii=False))
        raise SystemExit(1)
