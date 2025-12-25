from pathlib import Path


def test_alembic_ini_present():
    assert Path("alembic.ini").exists() or Path("backend/alembic.ini").exists()
