from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from app.db import models
from app.ingest import options_flow
from app.utils.hashing import sha256_file


@dataclass(frozen=True)
class OptionsFlowImportResult:
    sessions_touched: int
    rows_imported: int


_DATE_ANYWHERE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _repo_root_from_app_file(app_file: Path) -> Path:
    # app_file is expected somewhere under backend/app/**
    # backend/app/... -> parents[2] is backend, parents[3] is repo root
    return app_file.resolve().parents[3]


def _sample_data_dir() -> Path:
    return _repo_root_from_app_file(Path(__file__)) / "sample_data"


def _options_flow_dir() -> Path:
    return _sample_data_dir() / "options_flow"


def _extract_date_from_filename(name: str) -> date | None:
    m = _DATE_ANYWHERE_RE.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_timestamp_to_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        # Try several common formats
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.date()
            except ValueError:
                continue
        try:
            dt = pd.to_datetime(s, errors="coerce")
            if pd.isna(dt):
                return None
            return dt.to_pydatetime().date()
        except Exception:
            return None

    try:
        dt = pd.to_datetime(v, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.to_pydatetime().date()
    except Exception:
        return None


def _minimize_options_flow_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    # Keep the core fields used by aggregation + intent buckets; include ticker/underlying and side if present.
    keep_keys = {
        "ticker",
        "underlying",
        "underlying_symbol",
        "symbol",
        "side",
        "timestamp",
        "ts",
        "overpay_score",
        "overpay",
        "aggressive_score",
        "aggressive",
        "gamma_exposure",
        "gamma",
    }
    minimized: list[dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        out = {k: r.get(k) for k in keep_keys if k in r}
        # If minimization would drop everything, fall back to original.
        minimized.append(out if out else r)
    return minimized


def import_local_options_flow_file(
    *, db, filename: str, start_date: date | None = None, end_date: date | None = None
) -> OptionsFlowImportResult:
    """Import a local options flow CSV from sample_data/options_flow into per-session RawFile rows.

    - If filename contains a YYYY-MM-DD date, imports as a single session.
    - Otherwise, requires a per-row timestamp/date column and will group rows by date.
    """

    path = _options_flow_dir() / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    file_checksum = sha256_file(path)

    # Fast path: if filename contains a date, treat the whole file as that session.
    single_date = _extract_date_from_filename(path.name)

    parsed = options_flow.parse_options_flow(path)
    records = _minimize_options_flow_records(parsed.rows)

    by_date: dict[date, list[dict[str, Any]]] = {}
    if single_date:
        by_date[single_date] = records
    else:
        # Try grouping by timestamp/date column.
        # Prefer 'timestamp' but also tolerate 'date'/'ts'.
        for row in records:
            d = _parse_timestamp_to_date(row.get("timestamp") or row.get("date") or row.get("ts"))
            if not d:
                continue
            by_date.setdefault(d, []).append(row)

        if not by_date:
            raise ValueError(
                "Could not infer a session date. Either name the file with YYYY-MM-DD or include a timestamp/date column."
            )

    sessions_touched = 0
    rows_imported = 0

    for asof_date, day_rows in sorted(by_date.items()):
        if start_date and asof_date < start_date:
            continue
        if end_date and asof_date > end_date:
            continue
        session = db.query(models.Session).filter(models.Session.date == asof_date).first()
        if not session:
            session = models.Session(date=asof_date, strategy_mode=models.StrategyMode.INDEX_EOD)
            db.add(session)
            db.commit()
            db.refresh(session)

        session_id = str(session.session_id)
        per_day_checksum = file_checksum
        try:
            # Salt by date so a multi-day file becomes multi-session dedupe keys.
            import hashlib

            per_day_checksum = hashlib.sha256(f"{file_checksum}:{asof_date.isoformat()}".encode("utf-8")).hexdigest()
        except Exception:
            pass

        existing_id = (
            db.query(models.RawFile.file_id)
            .filter(
                models.RawFile.session_id == session_id,
                models.RawFile.source == models.RawSource.OPTIONS_FLOW,
                models.RawFile.sha256 == per_day_checksum,
            )
            .first()
        )
        if existing_id:
            continue

        raw_file = models.RawFile(
            session_id=session_id,
            source=models.RawSource.OPTIONS_FLOW,
            filename=f"{path.name}::{asof_date.isoformat()}",
            sha256=per_day_checksum,
            rows=len(day_rows),
            extras={"headers": parsed.headers, "rows": day_rows},
            parse_status=models.ParseStatus.OK,
        )
        db.add(raw_file)
        db.add(
            models.LogMessage(
                session_id=session_id,
                level=models.LogLevel.INFO,
                message=f"Imported local options flow {path.name}",
                context={"source": models.RawSource.OPTIONS_FLOW.value, "rows": len(day_rows)},
            )
        )
        db.commit()

        sessions_touched += 1
        rows_imported += len(day_rows)

    return OptionsFlowImportResult(sessions_touched=sessions_touched, rows_imported=rows_imported)
