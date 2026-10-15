"""Extract the supplied XLSX enum IDs as exact text, without float conversion."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
SHEETS = {"省份、区市、县": "regions", "一二类及子类": "products12", "三类及子类": "products3",
          "大客户分类": "customerCategories", "是否": "yesNo", "产品类型": "productTypes",
          "项目类型": "projectTypes", "场站类型分类": "stationTypes"}
STATION_GROUPS = {"field0020": "productTypes", "field0022": "projectTypes",
                  "field0404": "yesNo", "field0185": "stationTypes"}
HEADERS = {"A": "ID", "B": "枚举值显示名称", "C": "枚举值", "D": "PARENT_ID"}


def import_mapping(source: Path):
    groups = {}
    with ZipFile(source) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(t.text or "" for t in item.findall(".//x:t", NS))
                      for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("x:si", NS)]
        relationships = {rel.get("Id"): rel.get("Target") for rel in
                         ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        sheets = ET.fromstring(archive.read("xl/workbook.xml")).findall("x:sheets/x:sheet", NS)
        for sheet in sheets:
            group = SHEETS.get(sheet.get("name"))
            if group is None:
                continue
            target = relationships[sheet.get(REL_ID)]
            sheet_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            rows = ET.fromstring(archive.read(sheet_path)).findall("x:sheetData/x:row", NS)
            entries = {}
            for index, row in enumerate(rows):
                values = {}
                for cell in row.findall("x:c", NS):
                    column = re.sub(r"\d+$", "", cell.get("r", ""))
                    if column not in HEADERS:
                        continue
                    if cell.find("x:f", NS) is not None:
                        raise ValueError(f"{sheet.get('name')}!{cell.get('r')}: mapping must contain literal values")
                    value_node = cell.find("x:v", NS)
                    kind = cell.get("t", "n")
                    raw = value_node.text if value_node is not None else ""
                    if kind == "s":
                        value = shared[int(raw)]
                    elif kind == "inlineStr":
                        value = "".join(t.text or "" for t in cell.findall(".//x:t", NS))
                    else:
                        value = raw
                    value = value.strip()
                    if index and column in ("A", "D") and kind == "n" and len(value.lstrip("-")) > 15:
                        raise ValueError(f"{sheet.get('name')}!{cell.get('r')}: long IDs must be stored as text")
                    values[column] = value
                if index == 0:
                    if values != HEADERS:
                        raise ValueError(f"Unexpected headers: {sheet.get('name')}")
                    continue
                if not any(values.values()):
                    continue
                if set(values) != set(HEADERS) or not values["B"]:
                    raise ValueError(f"Incomplete mapping row: {sheet.get('name')}!{row.get('r')}")
                for column in ("A", "D"):
                    if not re.fullmatch(r"-?\d+", values[column]):
                        raise ValueError(f"Invalid ID: {sheet.get('name')}!{column}{row.get('r')}")
                entry = {"label": values["B"], "value": values["C"], "parentId": values["D"]}
                if values["A"] in entries and entries[values["A"]] != entry:
                    raise ValueError(f"Conflicting enum ID: {sheet.get('name')}!{row.get('r')}")
                entries[values["A"]] = entry
            if not entries or group in groups:
                raise ValueError(f"Empty or duplicate mapping sheet: {sheet.get('name')}")
            groups[group] = entries
    if set(groups) != set(SHEETS.values()):
        missing = [name for name, group in SHEETS.items() if group not in groups]
        raise ValueError("Required enum mapping sheets are missing: " + "、".join(missing))
    return {"source": {"name": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
            "groups": groups}


def station_mapping(mapping):
    return {"source": mapping["source"],
            "fields": {column: {key: entry["label"] for key, entry in mapping["groups"][group].items()}
                       for column, group in STATION_GROUPS.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "config/contract_ledger_enums.json")
    args = parser.parse_args()
    mapping = import_mapping(args.source)
    station = station_mapping(mapping)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    station_output = args.output.with_name("station_type_enums.json")
    station_output.write_text(json.dumps(station, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"entries": {key: len(values) for key, values in mapping["groups"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
