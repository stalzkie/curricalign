# backend/app/services/pdf_report.py
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv

# 🔑 MODERN SDK IMPORTS
from google import genai
from google.genai import types 

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors

from ..core.supabase_client import supabase

# ----------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 🎯 REVISED: Initialize the modern client globally
client: Optional[genai.Client] = None
if GEMINI_API_KEY:
    try:
        client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(api_version='v1')
        )
    except Exception as e:
        print(f"⚠️ Failed to initialize Gemini client: {e}")
        client = None

# Resolve the static/reports directory *absolutely* so prod == local.
# This matches what main.py mounts at /static.
# Path(__file__) -> .../backend/app/services/pdf_report.py
# parents[1]      -> .../backend/app
DEFAULT_REPORT_DIR = (Path(__file__).resolve().parents[1] / "static" / "reports").resolve()

# Allow an env override just in case (keeps behavior predictable in Railway),
# but default to the known-good static/reports path.
REPORT_OUTPUT_DIR = Path(os.getenv("REPORTS_DIR", str(DEFAULT_REPORT_DIR))).resolve()
REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"[pdf_report] REPORT_OUTPUT_DIR={REPORT_OUTPUT_DIR}")

# ----------------------------------------------------------------------
# AI SUMMARY GENERATION
# ----------------------------------------------------------------------
def generate_ai_summary(report_data: List[Dict[str, Any]]) -> str:
    if not report_data:
        return "No report data available to generate a summary."

    course_summaries = []
    for item in report_data:
        # Normalize skills for prompt readability
        skills_taught_str = ", ".join(item.get("skills_taught", [])[:5])
        skills_in_market_str = ", ".join(item.get("skills_in_market", [])[:5])
        course_summaries.append(
            f"{item.get('course_title', 'N/A')} ({item.get('course_code', 'N/A')}): "
            f"score {item.get('score', 0)}%, "
            f"taught {skills_taught_str or 'None'}, matched {skills_in_market_str or 'None'}"
        )

    prompt = f"""
You are an education and job market analyst. Given the following course alignment data:

{chr(10).join(course_summaries)}

Write an executive summary that:
1. Highlights the strongest and weakest courses based on the 'score'.
2. Identifies common skills missing from the curriculum (present in 'matched' but not 'taught').
3. Recommends areas of improvement.

Keep it under 200 words.
"""
    if not client:
        return "AI summary unavailable (Gemini client failed to initialize)."

    try:
        # 🎯 UPDATED: Use the client.models service to call generate_content
        response = client.models.generate_content(
            model="gemini-2.5-flash", # Using a fast model for text summarization
            contents=prompt
        )
        return (response.text or "").strip() or "Summary generation returned empty text."
    except Exception as e:
        print(f"⚠️ Failed to generate AI summary: {e}")
        return "Summary generation failed."

# ----------------------------------------------------------------------
# Data helpers
# ----------------------------------------------------------------------
def _as_list(x: Any) -> List[str]:
    if x is None:
        return []
    if isinstance(x, list):
        return [str(s).strip() for s in x if str(s).strip()]
    if isinstance(x, str):
        s = x.strip()
        if s.startswith("{") and s.endswith("}"):
            s = s[1:-1]
        return [t.strip() for t in s.split(",") if t.strip()]
    return []

def _as_float01(x: Any) -> float:
    try:
        v = float(x)
        return max(0.0, min(1.0, v))
    except Exception:
        return 0.0

def _as_int100(x: Any) -> int:
    try:
        v = int(round(float(x)))
        return max(0, min(100, v))
    except Exception:
        return 0

# ----------------------------------------------------------------------
# DATA FETCH (from course_alignment_scores_clean)
# ----------------------------------------------------------------------
def fetch_clean_report_data() -> List[Dict[str, Any]]:
    """
    Fetch most recent batch from course_alignment_scores_clean and normalize types.
    """
    try:
        latest_row = (
            supabase.table("course_alignment_scores_clean")
            .select("batch_id, calculated_at")
            .order("calculated_at", desc=True)
            .limit(1)
            .execute()
        )

        if not latest_row.data:
            print("⚠️ No cleaned data found in course_alignment_scores_clean.")
            return []

        latest_batch_id = latest_row.data[0]["batch_id"]

        result = (
            supabase.table("course_alignment_scores_clean")
            .select("*")
            .eq("batch_id", latest_batch_id)
            .execute()
        )

        rows: List[Dict[str, Any]] = []
        for row in result.data or []:
            rows.append(
                {
                    "course_id": row.get("course_id"),
                    "course_code": str(row.get("course_code", "N/A")),
                    "course_title": str(row.get("course_title", "N/A")),
                    "skills_taught": _as_list(row.get("skills_taught")),
                    "skills_in_market": _as_list(row.get("skills_in_market")),
                    "matched_job_skill_ids": _as_list(row.get("matched_job_skill_ids")),
                    "score": _as_int100(row.get("score", 0)),
                    "coverage": _as_float01(row.get("coverage", 0.0)),
                    "avg_similarity": _as_float01(row.get("avg_similarity", 0.0)),
                }
            )

        # Sort by score desc for nicer presentation
        rows.sort(key=lambda r: r.get("score", 0), reverse=True)

        print(f"✅ Retrieved {len(rows)} cleaned rows from batch {latest_batch_id}")
        return rows

    except Exception as e:
        print(f"❌ Error fetching cleaned report data: {e}")
        return []

# ----------------------------------------------------------------------
# PDF GENERATION
# ----------------------------------------------------------------------
def _default_filename() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"syllabus_job_alignment-{ts}.pdf"

def _sanitize_filename(name: str) -> str:
    # Keep it simple: alnum, dash, underscore, dot
    safe = "".join(ch for ch in name if ch.isalnum() or ch in ("-", "_", "."))
    return safe or _default_filename()

def generate_pdf_report(report_data: List[Dict[str, Any]], filename: Optional[str] = None) -> str:
    """
    Render the PDF to the static/reports directory and return the ABSOLUTE path.
    Raises a clear error if the file isn't created or is empty.
    """
    if not report_data:
        raise ValueError("No rows to render in PDF.")

    if not filename:
        filename = _default_filename()
    filename = _sanitize_filename(filename)

    # Absolute, inside the mounted static directory
    save_path = (REPORT_OUTPUT_DIR / filename).resolve()

    print(f"[pdf_report] Preparing to write PDF:")
    print(f"  - rows: {len(report_data)}")
    print(f"  - output dir exists: {REPORT_OUTPUT_DIR.exists()}")
    print(f"  - save_path: {save_path}")

    # Ensure the directory still exists at runtime (just in case)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(save_path),
        pagesize=landscape(A4),
        rightMargin=50,
        leftMargin=50,
        topMargin=50,
        bottomMargin=50,
        title="Curriculum vs Job Market Alignment Report",
        author="CurricAlign",
    )

    story = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=16, spaceAfter=20, alignment=1)
    body_style = ParagraphStyle("BodyText", parent=styles["Normal"], fontSize=10, leading=12, spaceAfter=12)
    footer_style = ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, spaceBefore=20, leading=10)

    # Title
    story.append(Paragraph("📘 Curriculum vs Job Market Alignment Report", title_style))

    # Executive Summary
    summary = generate_ai_summary(report_data)
    story.append(Paragraph("<b>📊 Executive Summary</b>", body_style))
    story.append(Paragraph(summary, body_style))
    story.append(Spacer(1, 0.2 * inch))

    # Table headers
    headers = ["Course Code", "Course Title", "Skills Taught", "Skills in Market", "Score", "Coverage", "Avg. Similarity"]
    table_data = [headers]

    for entry in report_data:
        row = [
            Paragraph(str(entry.get("course_code", "N/A")), styles["Normal"]),
            Paragraph(str(entry.get("course_title", "N/A")), styles["Normal"]),
            # Limiting the number of skills in the PDF for space
            Paragraph("<br/>".join(entry.get("skills_taught", [])[:7]) or "—", styles["Normal"]),
            Paragraph("<br/>".join(entry.get("skills_in_market", [])[:7]) or "—", styles["Normal"]),
            str(entry.get("score", 0)),
            f"{float(entry.get('coverage', 0.0)):.2f}",
            f"{float(entry.get('avg_similarity', 0.0)):.2f}",
        ]
        table_data.append(row)

    table = Table(table_data, colWidths=[1*inch, 2*inch, 2*inch, 2*inch, 0.7*inch, 0.8*inch, 0.9*inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )
    story.append(table)

    # Footer
    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph(f"Date Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", footer_style))
    story.append(Paragraph("<b>Note on the formula:</b> <i>score = int(avg_similarity * coverage * 100)</i>", footer_style))

    # Build the PDF
    doc.build(story)

    # Verify output exists and has content
    exists = save_path.exists()
    size = save_path.stat().st_size if exists else 0
    print(f"✅ Final PDF report saved to: {save_path} (exists={exists}, size={size})")

    if not exists or size <= 0:
        raise RuntimeError(f"PDF not found or empty at {save_path}")

    return str(save_path)

# ----------------------------------------------------------------------
# MAIN EXECUTION
# ----------------------------------------------------------------------
if __name__ == "__main__":
    data = fetch_clean_report_data()
    if data:
        path = generate_pdf_report(data)
        print(f"✅ Final PDF generated at: {path}")
    else:
        print("❌ Could not generate report. No cleaned data found.")