import sys
import os
import re
from pathlib import Path
from datetime import datetime, date
import traceback

# Add backend to path
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.append(str(BACKEND_ROOT))

from app.db.engine import SessionLocal
from app.db import models
from app.api.routes import _dispatch_parser, _aggregate_for_session
from app.features.build_v0 import build_feature_row
from app.regime.classify_v0 import classify
from app.briefs.generate_v1 import generate_briefs
from app.utils.hashing import sha256_file

def get_latest_date(sample_dir: Path) -> date | None:
    # Find latest date from filenames like *-YYYY-MM-DD.csv
    latest = None
    pattern = re.compile(r".*-(\d{4}-\d{2}-\d{2})\.csv")
    for f in sample_dir.glob("*.csv"):
        m = pattern.match(f.name)
        if m:
            try:
                d_str = m.group(1)
                d = datetime.strptime(d_str, "%Y-%m-%d").date()
                if latest is None or d > latest:
                    latest = d
            except ValueError:
                continue
    return latest

def process_daily():
    sample_dir = REPO_ROOT / "sample_data"
    latest_date = get_latest_date(sample_dir)
    
    if not latest_date:
        print("No dated files found in sample_data")
        return

    print(f"Processing data for {latest_date}...")
    
    db = SessionLocal()
    try:
        # 1. Create or Get Session
        session = db.query(models.Session).filter(models.Session.date == latest_date).first()
        if not session:
            print(f"Creating session for {latest_date}")
            session = models.Session(date=latest_date, strategy_mode=models.StrategyMode.INDEX_EOD)
            db.add(session)
            db.commit()
            db.refresh(session)
        else:
            print(f"Session for {latest_date} already exists. ID: {session.session_id}")

        session_id = str(session.session_id)

        # 2. Ingest Files
        source_map = {
            "bot-eod-report": models.RawSource.BOT_EOD,
            "chain-oi-changes": models.RawSource.OI_DIFF,
            "dp-eod-report": models.RawSource.DARKPOOL_EOD,
            "hot-chains": models.RawSource.HOT_CHAINS,
            "stock-screener": models.RawSource.STOCK_SCREENER,
        }

        for f in sample_dir.glob(f"*{latest_date}.csv"):
            source = None
            for key, val in source_map.items():
                if key in f.name:
                    source = val
                    break
            
            if not source:
                continue

            existing = db.query(models.RawFile).filter(
                models.RawFile.session_id == session_id,
                models.RawFile.filename == f.name
            ).first()
            
            if existing:
                print(f"File {f.name} already ingested.")
                continue

            print(f"Ingesting {f.name} as {source.value}...")
            parsed = _dispatch_parser(source, f)
            checksum = sha256_file(f)
            
            raw_file = models.RawFile(
                session_id=session_id,
                source=source,
                filename=f.name,
                sha256=checksum,
                rows=len(parsed.rows),
                extras={"headers": parsed.headers, "rows": parsed.rows},
                parse_status=models.ParseStatus.OK if not parsed.errors else models.ParseStatus.ERROR,
                error_message=";".join(parsed.errors) if parsed.errors else None,
            )
            db.add(raw_file)
            db.commit()

        # 3. Compute Features & Classify (V0)
        print("Aggregating data...")
        per_underlying = _aggregate_for_session(session_id, db)
        
        for underlying, aggregates in per_underlying.items():
            # Build Feature Row
            feature_row = build_feature_row(session_id, underlying, latest_date, aggregates)
            
            # Check existing feature
            existing_feature = db.query(models.FeaturesUnderlyingDay).filter_by(
                session_id=session_id, underlying=underlying, asof_date=latest_date
            ).first()

            if existing_feature:
                # Update
                for key, value in feature_row.__dict__.items():
                    if not key.startswith("_"):
                        setattr(existing_feature, key, value)
                feature_to_classify = existing_feature
            else:
                # Insert
                db.add(feature_row)
                feature_to_classify = feature_row
            
            db.commit() # Commit to ensure ID/state is ready

            # Classify
            decision_row = classify(feature_to_classify)
            
            existing_decision = db.query(models.RegimeDecision).filter_by(
                session_id=session_id, underlying=underlying, asof_date=latest_date
            ).first()

            if existing_decision:
                for key, value in decision_row.__dict__.items():
                    if not key.startswith("_"):
                        setattr(existing_decision, key, value)
            else:
                db.add(decision_row)
            
            db.commit()

        # 4. Generate Briefs
        print("Generating Daily Briefs...")
        briefs = generate_briefs(session_id, db)
        print(f"Generated {len(briefs)} briefs.")
        
        print("Daily processing complete.")
        print("Requesting updated files for next run...")

    except Exception as e:
        print(f"Error during processing: {e}")
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    process_daily()
