from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class ParsedCSV:
    headers: List[str]
    rows: List[Dict[str, Any]]
    errors: List[str] | None = None
