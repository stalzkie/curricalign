# apps/backend/api/endpoints/scan_pdf.py
from __future__ import annotations

import logging
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any

from ...services.scan_pdf import scan_pdf_and_store

router = APIRouter()
logger = logging.getLogger(__name__)

class ScanResponse(BaseModel):
    inserted: List[Dict[str, Any]]
    parsed_rows: List[Dict[str, Any]]
    raw_text_len: int

@router.post("/scan-pdf", response_model=ScanResponse)
async def scan_pdf_endpoint(pdf: UploadFile = File(...)):
    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    file_bytes = await pdf.read()
    try:
        out = scan_pdf_and_store(file_bytes)
        return out
    except Exception as e:
        # Log full stack for debugging while returning a clean 500 to client
        logger.exception("scan_pdf failed")
        raise HTTPException(status_code=500, detail=str(e))
