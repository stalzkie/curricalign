from fastapi import APIRouter
from ...services.pdf_report import generate_pdf_report

router = APIRouter()

@router.get("/generate")
def generate_report():
    report_data = generate_pdf_report()
    return {"message": "PDF report generated successfully", "report": report_data}
