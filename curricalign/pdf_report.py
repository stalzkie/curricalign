import os
import tempfile
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from dotenv import load_dotenv
import google.generativeai as genai
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib import colors

# NOTE: This assumes you have a supabase_client.py file
# with your Supabase client configuration.
from supabase_client import supabase

# --- CONFIGURATION ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# --- PDF REPORT GENERATION FUNCTIONS ---
def generate_ai_summary(report_data):
    """
    Uses Gemini (Google Generative AI) to generate an executive summary based on the report data.
    
    Args:
        report_data (list): The data used to create the report.
    
    Returns:
        str: The generated executive summary.
    """
    course_summaries = []
    for item in report_data:
        # Convert list of skills to a comma-separated string for the prompt
        skills_taught_str = ", ".join(item['skills_taught'])
        skills_in_market_str = ", ".join(item['skills_in_market'])
        
        course_summaries.append(
            f"{item['course_title']}: score {item['score']}%, taught {skills_taught_str}, matched {skills_in_market_str}"
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

    try:
        model = genai.GenerativeModel("gemini-1.5-pro")
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        # In a real-world application, you would log this error.
        print(f"⚠️ Failed to generate AI summary (Gemini): {e}")
        return "Summary generation failed."

def fetch_report_data_from_supabase():
    """
    Fetches the final calculated report data from the Supabase table.
    
    Returns:
        list: A list of dictionaries with the report data, or an empty list if an error occurs.
    """
    try:
        print("📦 Fetching report data from Supabase...")
        result = supabase.table("course_alignment_scores").select("*").execute()
        
        if result.data:
            report_data = []
            for row in result.data:
                # Assuming the skills are stored as comma-separated strings
                skills_taught_list = [s.strip() for s in row.get("skills_taught", "").split(',') if s.strip()]
                skills_in_market_list = [s.strip() for s in row.get("skills_in_market", "").split(',') if s.strip()]

                report_data.append({
                    "course_code": row.get("course_code", "N/A"),
                    "course_title": row.get("course_title", "N/A"),
                    "skills_taught": skills_taught_list,
                    "skills_in_market": skills_in_market_list,
                    "score": row.get("score", 0),
                    "coverage": row.get("coverage", 0.0),
                    "avg_similarity": row.get("avg_similarity", 0.0),
                })
            print(f"✅ Successfully fetched {len(report_data)} records.")
            return report_data
        else:
            print("⚠️ No data found in the 'course_alignment_scores' table.")
            return []
    except Exception as e:
        print(f"❌ Failed to fetch data from Supabase: {e}")
        return []

def generate_pdf_report(report_data, filename="syllabus_job_alignment.pdf"):
    """
    Generates a multi-page PDF report using ReportLab's Platypus framework in landscape orientation.
    """
    # Create a document template with landscape orientation
    doc = SimpleDocTemplate(
        filename,
        pagesize=landscape(A4),
        rightMargin=50,
        leftMargin=50,
        topMargin=50,
        bottomMargin=50
    )

    story = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, spaceAfter=20, alignment=1)
    body_style = ParagraphStyle('BodyText', parent=styles['Normal'], fontSize=10, leading=12, spaceAfter=12)
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, spaceBefore=20, leading=10)

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
        "Avg. Similarity"
    ]
    table_data = [headers]
    for entry in report_data:
        skills_taught = "<br/>".join(entry["skills_taught"])
        skills_in_market = "<br/>".join(entry["skills_in_market"])
        
        row = [
            Paragraph(str(entry["course_code"]), styles['Normal']),
            Paragraph(str(entry["course_title"]), styles['Normal']),
            Paragraph(skills_taught, styles['Normal']),
            Paragraph(skills_in_market, styles['Normal']),
            str(entry["score"]),
            f"{entry['coverage']:.2f}",
            f"{entry['avg_similarity']:.2f}"
        ]
        table_data.append(row)

    # Distribute the width of a landscape A4 page (742 points total)
    table_col_widths = [1.0*inch, 2.0*inch, 2.0*inch, 2.0*inch, 0.7*inch, 0.8*inch, 0.9*inch]
    table = Table(table_data, colWidths=table_col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3)
    ]))
    story.append(table)

    # Add footer information
    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph(f"**Date Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", footer_style))
    story.append(Paragraph("<b>Note on the formula:</b> <i>score = int(avg_similarity * coverage * 100)</i>", footer_style))

    doc.build(story)

# --- MAIN EXECUTION BLOCK ---
if __name__ == "__main__":
    report_data = fetch_report_data_from_supabase()

    if report_data:
        generate_pdf_report(report_data)
        print("✅ Final PDF report generated successfully!")
    else:
        print("❌ Could not generate report. No data to display.")