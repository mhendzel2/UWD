#!/usr/bin/env python3
"""Quick DB check script."""
import sys
sys.path.insert(0, ".")

from app.db.engine import engine
from sqlalchemy import text

with engine.connect() as conn:
    # Check tables
    r = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"))
    print("Tables:", [x[0] for x in r.fetchall()])
    
    # Check enum types
    r = conn.execute(text("SELECT typname, enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid ORDER BY typname, enumsortorder"))
    print("\nEnum values:")
    for row in r.fetchall():
        print(f"  {row[0]}: {row[1]}")
