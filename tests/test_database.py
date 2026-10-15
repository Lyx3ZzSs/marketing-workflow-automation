from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from sqlalchemy.dialects import mysql
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from database import create_ledger_engine


class DatabaseTests(unittest.TestCase):
    def test_engine_encodes_credentials_and_uses_repeatable_snapshot(self):
        credentials = {"host": "example.test", "user": "reader", "password": "p@ss:/%word", "database": "ledger"}
        with patch("database.read_credentials", return_value=credentials), patch("database.create_engine") as factory:
            create_ledger_engine(Path("unused"))
        url = factory.call_args.args[0]
        self.assertEqual(url.password, credentials["password"])
        self.assertNotIn(credentials["password"], str(url))
        self.assertEqual(factory.call_args.kwargs["isolation_level"], "REPEATABLE READ")
        self.assertTrue(factory.call_args.kwargs["hide_parameters"])

    def test_mysql_binding_preserves_literal_search_and_long_id(self):
        statement = text("SELECT ID FROM formmain_8861 WHERE BINARY field0008 = BINARY :plant AND ID <> :id")
        compiled = statement.bindparams(plant="电厂%_\\'名称", id="9000000000000000001").compile(dialect=mysql.dialect())
        self.assertNotIn("电厂", str(compiled))
        self.assertEqual(compiled.params, {"plant": "电厂%_\\'名称", "id": "9000000000000000001"})
