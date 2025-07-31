import os
import tempfile
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
import google.generativeai as genai

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def generate_ai_summary(report_data):
    """
    Uses Gemini (Google Generative AI) to generate an executive summary.
    """
    course_summaries = []
    for item in report_data:
        course_summaries.append(
            f"{item['course']}: score {item['score']}%, taught {item['skills_taught']}, matched {item['skills_in_market']}"
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
        print(f"⚠️ Failed to generate AI summary (Gemini): {e}")
        return "Summary generation failed."

def generate_pdf_report(report_data, filename="syllabus_job_alignment.pdf"):
    c = canvas.Canvas(filename, pagesize=A4)
    width, height = A4
    margin = 50
    y = height - margin

    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, "📘 Curriculum vs Job Market Alignment Report")
    y -= 30

    # AI Executive Summary
    summary = generate_ai_summary(report_data)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "📊 Executive Summary")
    y -= 20
    c.setFont("Helvetica", 9)
    for line in summary.splitlines():
        c.drawString(margin, y, line.strip())
        y -= 12
    y -= 10

    # Table
    headers = ["Course", "Score (%)", "Skills Taught", "Matched Skills"]
    data = [headers]

    for entry in report_data:
        row = [
            entry["course"][:35] + ("..." if len(entry["course"]) > 35 else ""),
            str(entry["score"]),
            ", ".join(entry["skills_taught"])[:50] + "...",
            ", ".join(entry["skills_in_market"])[:50] + "..."
        ]
        data.append(row)

    table = Table(data, colWidths=[170, 60, 150, 150])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
    ]))

    table.wrapOn(c, width, height)
    table_height = 20 * len(data)
    table.drawOn(c, margin, y - table_height)

    y -= table_height + 40

    # Chart section
    chart_paths = []
    try:
        labels = [e["course"][:20] for e in report_data]
        scores = [e["score"] for e in report_data]

        plt.figure(figsize=(8, 4))
        plt.barh(labels, scores, color='skyblue')
        plt.xlabel("Success Score")
        plt.title("Subject-to-Market Alignment")
        plt.tight_layout()

        chart1 = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        chart1.close()
        plt.savefig(chart1.name)
        chart_paths.append(chart1.name)
        plt.close()

        c.drawImage(chart1.name, margin, 50, width=500, height=200)
    except Exception as e:
        print(f"⚠️ Failed to generate chart: {e}")

    c.save()

    for path in chart_paths:
        os.remove(path)
