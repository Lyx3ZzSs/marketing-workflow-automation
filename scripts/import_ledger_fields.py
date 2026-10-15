"""Import the user-provided ledger field list and validate against a local schema snapshot."""
import argparse
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--schema-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    text = args.source.read_text(encoding="utf-8-sig")
    table_match = re.search(r"数据库表名称[：:]\s*(\w+)", text)
    if not table_match:
        raise ValueError("字段明细未注明数据库表名称")
    snapshot = json.loads(args.schema_snapshot.read_text(encoding="utf-8"))
    if snapshot["verification"]["table"] != table_match.group(1):
        raise ValueError("字段明细和查询快照的表名称不一致")
    fields = []
    for number, line in enumerate(text.splitlines(), 1):
        if not re.match(r"^field\d+\t", line):
            continue
        parts = [part.strip() for part in re.split(r"\t *\t", line)]
        if len(parts) != 6:
            raise ValueError(f"第 {number} 行字段明细格式不符合六列结构")
        field = dict(zip(["column", "declared_type", "length", "display_name", "input_type", "final_type"], parts))
        if not field["display_name"]:
            raise ValueError(f"第 {number} 行缺少中文显示名称")
        fields.append(field)
    if not fields:
        raise ValueError("字段明细为空")
    names = [field["column"] for field in fields]
    if len(names) != len(set(names)):
        raise ValueError("字段明细中存在重复字段编号")
    actual = {column["Field"] for column in snapshot["columns"]}
    unknown = sorted(set(names) - actual)
    if unknown:
        raise ValueError(f"字段明细存在数据库主表中未找到的字段：{unknown}")
    unmapped = sorted(actual - set(names))
    result = {"table": table_match.group(1), "source_filename": args.source.name,
              "verified_against_snapshot_at": snapshot["verification"]["verified_at"],
              "business_field_count": len(fields), "database_column_count": len(actual),
              "columns_without_display_name": unmapped, "fields": fields}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"business_fields": len(fields), "database_columns": len(actual),
                      "all_business_fields_verified": True, "unmapped_columns": unmapped,
                      "output": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
