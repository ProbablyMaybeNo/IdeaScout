from pathlib import Path

import pytest

from ideascout.db import connect, init_schema


@pytest.fixture
def db(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    init_schema(conn)
    yield conn
    conn.close()
