"""SQLAlchemy engine for the existing, read-only Seeyon ledger."""
from pathlib import Path

from sqlalchemy import URL, create_engine

from verify_contract_ledger import read_credentials


def create_ledger_engine(document: Path):
    credentials = read_credentials(document)
    url = URL.create(
        "mysql+pymysql", username=credentials["user"], password=credentials["password"],
        host=credentials["host"], port=3306, database=credentials["database"],
        query={"charset": "utf8mb4"},
    )
    return create_engine(
        url, isolation_level="REPEATABLE READ", pool_pre_ping=True, pool_recycle=1800,
        pool_size=5, max_overflow=5, pool_timeout=8, hide_parameters=True,
        connect_args={"connect_timeout": 8, "read_timeout": 20, "write_timeout": 10},
    )
