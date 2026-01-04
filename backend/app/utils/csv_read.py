import csv
from pathlib import Path
from typing import List, Dict, Any, Tuple


def _dedupe_headers(headers: List[str]) -> List[str]:
    """Ensure CSV headers are unique by appending deterministic suffixes."""
    seen: dict[str, int] = {}
    deduped: list[str] = []
    for h in headers:
        count = seen.get(h, 0)
        if count == 0:
            deduped.append(h)
        else:
            deduped.append(f"{h}_{count}")
        seen[h] = count + 1
    return deduped


def read_csv(path: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    headers: List[str] = []
    rows: List[Dict[str, Any]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        raw_headers = reader.fieldnames or []
        headers = _dedupe_headers(raw_headers)
        reader.fieldnames = headers  # type: ignore[assignment]
        for raw in reader:
            cleaned = {k: (v if v not in ("", None) else None) for k, v in raw.items()}
            rows.append(cleaned)
    return headers, rows
