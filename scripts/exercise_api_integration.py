import os
from pathlib import Path

from fastapi.testclient import TestClient


def main() -> None:
    # Point backend at the Docker Postgres published on host port 5433.
    os.environ.setdefault(
        "UW_DATABASE_URL",
        "postgresql+psycopg2://uw_app:uw_password@127.0.0.1:5433/uw_eod",
    )

    from app.main import app  # imported after env var so Settings picks it up

    client = TestClient(app)

    r = client.get("/health")
    r.raise_for_status()
    print("health:", r.json())

    r = client.post(
        "/sessions",
        data={"session_date": "2025-12-24", "strategy_mode": "INDEX_EOD"},
    )
    r.raise_for_status()
    session_id = r.json()["session_id"]
    print("session_id:", session_id)

    repo_root = Path(__file__).resolve().parents[1]

    samples = [
        ("OI_DIFF", repo_root / "sample_data" / "chain-oi-changes-2025-12-24.csv"),
        ("BOT_EOD", repo_root / "sample_data" / "bot-eod-report-2025-12-24.csv"),
        ("HOT_CHAINS", repo_root / "sample_data" / "hot-chains-2025-12-24.csv"),
        ("DARKPOOL_EOD", repo_root / "sample_data" / "dp-eod-report-2025-12-24.csv"),
        ("STOCK_SCREENER", repo_root / "sample_data" / "stock-screener-2025-12-24.csv"),
    ]

    for source, path in samples:
        if not path.exists():
            print("missing sample:", source, str(path))
            continue
        with path.open("rb") as f:
            files = {"file": (path.name, f, "text/csv")}
            data = {"session_id": session_id}
            r = client.post(f"/import/{source}", data=data, files=files)
            r.raise_for_status()
            print("import", source, r.json())

    r = client.post(
        "/compute/v0",
        data={"session_id": session_id, "asof_date": "2025-12-24"},
    )
    r.raise_for_status()
    decisions = r.json().get("decisions", [])
    print("compute decisions:", len(decisions))

    r = client.get(f"/sessions/{session_id}/summary")
    r.raise_for_status()
    summary = r.json()
    print("summary:", {k: (len(v) if isinstance(v, list) else v) for k, v in summary.items()})


if __name__ == "__main__":
    main()
