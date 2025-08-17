import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
import google.generativeai as genai

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors

# NOTE: This assumes you have a supabase_client.py file
# with your Supabase client configuration.
from ..core.supabase_client import supabase

# --- CONFIGURATION ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Where to save the generated PDFs:
# Resolve to: backend/static/reports
REPORT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "static" / "reports"
REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# --- PDF REPORT GENERATION FUNCTIONS ---
def generate_ai_summary(report_data: List[Dict[str, Any]]) -> str:
    """
    Uses Gemini (Google Generative AI) to generate an executive summary based on the report data.

    Args:
        report_data (list): The data used to create the report.

    Returns:
        str: The generated executive summary (<= ~200 words).
    """
    if not report_data:
        print("⚠️ No report data provided for AI summary generation.")
        return "No report data available to generate a summary."

    course_summaries = []
    for item in report_data:
        skills_taught_str = ", ".join(item.get("skills_taught", []))
        skills_in_market_str = ", ".join(item.get("skills_in_market", []))
        course_summaries.append(
            f"{item.get('course_title', 'N/A')}: score {item.get('score', 0)}%, "
            f"taught {skills_taught_str}, matched {skills_in_market_str}"
        )

    prompt = f"""
You are an education and job market analyst. Given the following course alignment data:

{chr(10).join(course_summaries)}

Write an executive summary that:
1. Highlights the strongest and weakest courses.
2. Identifies common skills missing from the curriculum.
3. Recommends areas of improvement.

Keep it under 200 words.
"""

    # If no API key or SDK not configured, fall back to a static message
    if not GEMINI_API_KEY:
        return "AI summary unavailable (no API key configured)."

    try:
        model = genai.GenerativeModel("gemini-1.5-pro")
        response = model.generate_content(prompt)
        return (response.text or "").strip() or "Summary generation returned empty text."
    except Exception as e:
        print(f"⚠️ Failed to generate AI summary (Gemini): {e}")
        return "Summary generation failed."


def fetch_report_data_from_supabase() -> List[Dict[str, Any]]:
    """
    Fetches the most recent full course alignment batch using the batch_id with the latest calculated_at.

    Returns:
        list: A list of dictionaries with the report data.
    """
    try:
        print("📦 Looking for the latest batch_id based on max calculated_at...")

        # Step 1: Get the batch_id with the latest calculated_at value
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

        # Step 2: Get all rows with this batch_id
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
                    "course_code": row.get("course_code", "N/A"),
                    "course_title": row.get("course_title", "N/A"),
                    "skills_taught": skills_taught_list,
                    "skills_in_market": skills_in_market_list,
                    "score": row.get("score", 0),
                    "coverage": row.get("coverage", 0.0),
                    "avg_similarity": row.get("avg_similarity", 0.0),
                }
            )

        print(f"✅ Retrieved {len(report_data)} entries from batch {latest_batch_id}")
        return report_data

    except Exception as e:
        print(f"❌ Error fetching report data: {e}")
        return []


def _default_filename() -> str:
    # Timestamped file name to avoid collisions/caching issues
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"syllabus_job_alignment-{ts}.pdf"


def generate_pdf_report(report_data: List[Dict[str, Any]], filename: Optional[str] = None) -> str:
    """
    Generates a multi-page PDF report (landscape A4) using ReportLab and saves it under:
        backend/static/reports/<filename>

    Args:
        report_data: list of dict entries for the table
        filename: optional; if not provided, a timestamped name is used

    Returns:
        str: absolute path to the saved PDF (use this to construct a download URL)
    """
    if not filename:
        filename = _default_filename()

    # Ensure directory exists
    REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_path = (REPORT_OUTPUT_DIR / filename).resolve()

    # Create a document template with landscape orientation
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

    # --- Build story ---
    story = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title", parent=styles["Heading1"], fontSize=16, spaceAfter=20, alignment=1
    )
    body_style = ParagraphStyle(
        "BodyText", parent=styles["Normal"], fontSize=10, leading=12, spaceAfter=12
    )
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"], fontSize=8, spaceBefore=20, leading=10
    )

    story.append(Paragraph("📘 Curriculum vs Job Market Alignment Report", title_style))

    summary = generate_ai_summary(report_data)
    story.append(Paragraph("<b>📊 Executive Summary</b>", body_style))
    story.append(Paragraph(summary, body_style))
    story.append(Spacer(1, 0.2 * inch))

    headers = [
        "Course Code",
        "Course Title",
        "Skills Taught",
        "Skills in Market",
        "Score",
        "Coverage",
        "Avg. Similarity",
    ]
    table_data = [headers]

    for entry in report_data:
        skills_taught = "<br/>".join(entry.get("skills_taught", []))
        skills_in_market = "<br/>".join(entry.get("skills_in_market", []))

        row = [
            Paragraph(str(entry.get("course_code", "N/A")), styles["Normal"]),
            Paragraph(str(entry.get("course_title", "N/A")), styles["Normal"]),
            Paragraph(skills_taught or "—", styles["Normal"]),
            Paragraph(skills_in_market or "—", styles["Normal"]),
            str(entry.get("score", 0)),
            f"{float(entry.get('coverage', 0.0)):.2f}",
            f"{float(entry.get('avg_similarity', 0.0)):.2f}",
        ]
        table_data.append(row)

    table_col_widths = [
        1.0 * inch,
        2.0 * inch,
        2.0 * inch,
        2.0 * inch,
        0.7 * inch,
        0.8 * inch,
        0.9 * inch,
    ]

    table = Table(table_data, colWidths=table_col_widths, repeatRows=1)
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
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)

    story.append(Spacer(1, 0.5 * inch))
    story.append(
        Paragraph(
            f"Date Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            footer_style,
        )
    )
    story.append(
        Paragraph(
            "<b>Note on the formula:</b> <i>score = int(avg_similarity * coverage * 100)</i>",
            footer_style,
        )
    )

    # Build the PDF
    doc.build(story)

    print(f"✅ Final PDF report saved to: {save_path}")
    return str(save_path)


# --- MAIN EXECUTION BLOCK ---
if __name__ == "__main__":
    data = fetch_report_data_from_supabase()
    if data:
        path = generate_pdf_report(data)  # returns absolute path
        print(f"✅ Final PDF report generated successfully at: {path}")
    else:
        print("❌ Could not generate report. No data was found or a database error occurred.")
