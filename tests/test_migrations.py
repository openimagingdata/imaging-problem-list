"""Tests for Alembic migration foundation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from alembic import command
from finding_extractor.db import tables as _tables  # noqa: F401
from finding_extractor.db.engine import StoreRuntime


def _alembic_config() -> Config:
    """Build Alembic config rooted at this repository."""
    return Config("alembic.ini")


def test_alembic_upgrade_creates_expected_tables(tmp_path: Path, monkeypatch) -> None:
    """Upgrading to head creates all core tables and Alembic version tracking."""
    db_path = tmp_path / "migration.sqlite3"
    monkeypatch.setenv("IPL_DB_PATH", str(db_path))

    command.upgrade(_alembic_config(), "head")

    with sqlite3.connect(db_path) as conn:
        table_names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        # Check for new columns
        reports_cols = {row[1] for row in conn.execute("PRAGMA table_info(reports)")}
        corrections_cols = {row[1] for row in conn.execute("PRAGMA table_info(corrections)")}
        extractions_cols = {row[1] for row in conn.execute("PRAGMA table_info(extractions)")}

    assert {
        "alembic_version",
        "reports",
        "extractions",
        "corrections",
        "jobs",
        "users",
    } <= table_names
    assert "patient_id" in reports_cols
    assert "section_structure_json" in reports_cols
    assert "username" in corrections_cols
    assert "laterality" in extractions_cols
    assert "finding_count" in extractions_cols
    assert "coded_finding_count" in extractions_cols
    assert "unresolved_finding_count" in extractions_cols
    assert "diagnostics_json" in extractions_cols
    assert "trace_id" in extractions_cols
    assert "coding_model" in extractions_cols
    assert "coding_reasoning" in extractions_cols
    assert "coding_completed_at" in extractions_cols
    assert "coding_duration_ms" in extractions_cols
    assert "coding_trace_id" in extractions_cols


def test_alembic_check_reports_no_drift_on_upgraded_db(tmp_path: Path, monkeypatch) -> None:
    """`alembic check` should report no pending ops after upgrade head."""
    db_path = tmp_path / "drift-check.sqlite3"
    monkeypatch.setenv("IPL_DB_PATH", str(db_path))
    config = _alembic_config()

    command.upgrade(config, "head")
    command.check(config)


def test_alembic_stamp_baseline_for_existing_create_all_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Existing pre-Alembic schema can be adopted with baseline stamp then upgrade to head."""
    db_path = tmp_path / "existing-schema.sqlite3"
    sqlite_url = f"sqlite:///{db_path}"
    engine = create_engine(sqlite_url)
    SQLModel.metadata.create_all(engine)

    monkeypatch.setenv("IPL_DB_PATH", str(db_path))
    config = _alembic_config()

    # create_all already materialises the current schema (including new columns),
    # so stamp head directly — migrations would redundantly ADD COLUMN.
    command.stamp(config, "head")

    with sqlite3.connect(db_path) as conn:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()

    assert version is not None
    assert version[0] == StoreRuntime.EXPECTED_REVISION
