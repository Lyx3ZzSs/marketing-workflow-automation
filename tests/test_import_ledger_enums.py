import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from import_ledger_enums import HEADERS, NS, REL_ID, SHEETS, STATION_GROUPS, import_mapping, station_mapping


def write_workbook(path, *, conflict=False, numeric_id=False, formula=False, sheet_names=None):
    namespace = NS["x"]
    workbook = ET.Element(f"{{{namespace}}}workbook")
    sheets = ET.SubElement(workbook, f"{{{namespace}}}sheets")
    relationships = ET.Element("Relationships")
    with ZipFile(path, "w") as archive:
        for index, name in enumerate(SHEETS if sheet_names is None else sheet_names, 1):
            ET.SubElement(sheets, f"{{{namespace}}}sheet", {"name": name, "sheetId": str(index), REL_ID: f"rId{index}"})
            ET.SubElement(relationships, "Relationship", {"Id": f"rId{index}", "Target": f"worksheets/sheet{index}.xml"})
            worksheet = ET.Element(f"{{{namespace}}}worksheet")
            data = ET.SubElement(worksheet, f"{{{namespace}}}sheetData")
            rows = [list(HEADERS.values()), ["-9000000000000000001", "测试名称 & 名称", "0", "9000000000000000002"]]
            if conflict:
                rows.append(["-9000000000000000001", "另一名称", "0", "9000000000000000002"])
            for row_number, values in enumerate(rows, 1):
                row = ET.SubElement(data, f"{{{namespace}}}row", {"r": str(row_number)})
                for column, value in zip(HEADERS, values):
                    kind = "n" if numeric_id and row_number == 2 and column == "A" else "inlineStr"
                    cell = ET.SubElement(row, f"{{{namespace}}}c", {"r": f"{column}{row_number}", "t": kind})
                    if formula and row_number == 2 and column == "B":
                        ET.SubElement(cell, f"{{{namespace}}}f").text = '"cached name"'
                    if kind == "n":
                        ET.SubElement(cell, f"{{{namespace}}}v").text = value
                    else:
                        inline = ET.SubElement(cell, f"{{{namespace}}}is")
                        ET.SubElement(inline, f"{{{namespace}}}t").text = value
            archive.writestr(f"xl/worksheets/sheet{index}.xml", ET.tostring(worksheet))
        archive.writestr("xl/workbook.xml", ET.tostring(workbook))
        archive.writestr("xl/_rels/workbook.xml.rels", ET.tostring(relationships))


class ImportTests(unittest.TestCase):
    def test_long_text_ids_and_parent_ids_are_preserved_exactly(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "mapping.xlsx"
            write_workbook(path)
            mapping = import_mapping(path)
        for group in mapping["groups"].values():
            self.assertEqual(group["-9000000000000000001"], {
                "label": "测试名称 & 名称", "value": "0", "parentId": "9000000000000000002"})
        self.assertEqual(len(mapping["source"]["sha256"]), 64)

    def test_conflicting_id_numeric_long_id_and_formula_are_rejected(self):
        for option in ("conflict", "numeric_id", "formula"):
            with self.subTest(option=option), TemporaryDirectory() as temporary:
                path = Path(temporary) / "mapping.xlsx"
                write_workbook(path, **{option: True})
                with self.assertRaises(ValueError):
                    import_mapping(path)

    def test_missing_station_sheet_is_rejected_before_import(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "mapping.xlsx"
            write_workbook(path, sheet_names=[name for name in SHEETS if name != "场站类型分类"])
            with self.assertRaisesRegex(ValueError, "场站类型分类"):
                import_mapping(path)

    def test_station_fields_use_their_respective_groups_and_share_provenance(self):
        mapping = {"source": {"name": "mapping.xlsx", "sha256": "test"}, "groups": {
            group: {str(-9000000000000000000 + i): {"label": group, "value": "0", "parentId": "0"}}
            for i, group in enumerate(STATION_GROUPS.values())}}
        station = station_mapping(mapping)
        self.assertEqual(station["source"], mapping["source"])
        for i, (column, group) in enumerate(STATION_GROUPS.items()):
            self.assertEqual(station["fields"][column], {str(-9000000000000000000 + i): group})


if __name__ == "__main__":
    unittest.main()
