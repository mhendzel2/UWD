import csv
from pathlib import Path
from typing import List, Dict, Any, Tuple


def read_csv(path: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    headers: List[str] = []
    rows: List[Dict[str, Any]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        for raw in reader:
            cleaned = {k: (v if v not in ("", None) else None) for k, v in raw.items()}
            rows.append(cleaned)
    return headers, rows
