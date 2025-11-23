from __future__ import annotations

import os
import csv
import logging
from typing import List, Dict, Any

from supabase import create_client, Client
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# ---------------- Logging ----------------
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s'
)

# ---------------- Env ----------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
COURSES_TABLE = os.getenv("COURSES_TABLE", "courses")
UPSERT_ON = os.getenv("COURSES_UPSERT_COLUMN", "course_code")

# Mock fallback if env not set (optional - you can delete this if you never mock)
if not SUPABASE_URL or not SUPABASE_KEY:
    class MockSupabaseClient:
        def table(self, name):
            return self
        def upsert(self, payload, on_conflict):
            logger.info(f"MOCK UPSERT: {len(payload)} rows into {name} (on_conflict={on_conflict})")
            class MockExec:
                def execute(self):
                    return type("obj", (object,), {"data": payload})()
            return MockExec()
    SB: Client = MockSupabaseClient()  # type: ignore
else:
    SB: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- Pydantic Model ----------------
class CourseRow(BaseModel):
    course_code: str = Field(..., min_length=1)
    course_title: str = Field(..., min_length=1)
    course_description: str = Field(..., min_length=1)

# ---------------- Helpers ----------------
def _norm_space(s: str) -> str:
    return " ".join((s or "").split()).strip()

def _canonical_code(code: str) -> str:
    return _norm_space(code).replace(" ", "").upper()

# ---------------- Supabase Upsert ----------------
def upsert_courses(rows: List[CourseRow]) -> List[Dict[str, Any]]:
    if not rows:
        return []
    payload = [r.model_dump() for r in rows]
    try:
        result = SB.table(COURSES_TABLE).upsert(payload, on_conflict=UPSERT_ON).execute()
        return result.data or []
    except Exception as e:
        logger.error("❌ Supabase upsert failed: %s", e)
        return []

# ---------------- CSV Scanner (for backend use) ----------------
def scan_csv_and_store(file_path: str) -> Dict[str, Any]:
    """
    Reads a CSV with columns:
      - course_code
      - course_title
      - course_description

    Validates and upserts directly into Supabase.
    """
    logger.info("🚀 Starting CSV course scan from %s…", file_path)
    rows: List[CourseRow] = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for line_number, row in enumerate(reader, start=1):
                try:
                    validated = CourseRow(
                        course_code=_canonical_code(row["course_code"]),
                        course_title=_norm_space(row["course_title"]).upper(),
                        course_description=_norm_space(row["course_description"])
                    )
                    rows.append(validated)
                except Exception as e:
                    logger.warning("⚠️ Skipping invalid CSV row #%d: %s | row=%s", line_number, e, row)

    except Exception as e:
        raise RuntimeError(f"CSV read failed: {e}")

    if not rows:
        raise RuntimeError("CSV contained 0 valid course rows.")

    logger.info("📚 Valid rows parsed from CSV: %d", len(rows))

    inserted = upsert_courses(rows)

    logger.info("✅ Parsed %d rows and inserted %d", len(rows), len(inserted))

    return {
        "parsed_rows": [r.model_dump() for r in rows],
        "inserted_rows": inserted,
        "total_parsed": len(rows),
        "total_inserted": len(inserted),
    }
