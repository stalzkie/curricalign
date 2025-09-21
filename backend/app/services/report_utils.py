# backend/app/services/report_utils.py
from typing import List, Dict, Any
from ..core.supabase_client import supabase


def fetch_report_data_from_supabase() -> List[Dict[str, Any]]:
    try:
        print("📦 Looking for the latest batch_id based on max calculated_at...")

        latest_row = (
            supabase.table("course_alignment_scores")
            .select("batch_id, calculated_at")
            .order("calculated_at", desc=True)
            .limit(1)
            .execute()
        )
        if not latest_row.data:
            print("⚠️ No data found in course_alignment_scores.")
            return []

        latest_batch_id = latest_row.data[0]["batch_id"]
        print(f"🆕 Using latest batch ID: {latest_batch_id}")

        result = (
            supabase.table("course_alignment_scores")
            .select("*")
            .eq("batch_id", latest_batch_id)
            .execute()
        )
        if not result.data:
            print(f"⚠️ No records found for batch_id {latest_batch_id}")
            return []

        report_data: List[Dict[str, Any]] = []
        for row in result.data:
            skills_taught_list = [
                s.strip() for s in (row.get("skills_taught") or "").split(",") if s.strip()
            ]
            skills_in_market_list = [
                s.strip() for s in (row.get("skills_in_market") or "").split(",") if s.strip()
            ]

            report_data.append(
                {
                    "batch_id": row.get("batch_id"),                 # ✅ needed
                    "course_id": row.get("course_id"),               # ✅ needed
                    "course_code": row.get("course_code", "N/A"),
                    "course_title": row.get("course_title", "N/A"),
                    "skills_taught": skills_taught_list,
                    "skills_in_market": skills_in_market_list,
                    "matched_job_skill_ids": row.get("matched_job_skill_ids"),  # keep if present
                    "score": int(row.get("score", 0) or 0),
                    "coverage": float(row.get("coverage", 0.0) or 0.0),
                    "avg_similarity": float(row.get("avg_similarity", 0.0) or 0.0),
                    "calculated_at": row.get("calculated_at"),
                }
            )

        print(f"✅ Retrieved {len(report_data)} entries from batch {latest_batch_id}")
        return report_data

    except Exception as e:
        print(f"❌ Error fetching report data: {e}")
        return []
