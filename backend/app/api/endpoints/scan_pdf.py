# apps/backend/api/endpoints/scan_pdf.py
from __future__ import annotations

import logging
import asyncio
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any

# import the updated service function
from ...services.scan_pdf import scan_pdf_and_store

router = APIRouter()
logger = logging.getLogger(__name__)

# Updated response model — matches new orchestrator output
class ScanResponse(BaseModel):
    inserted_count: int
    parsed_count: int
    raw_text_len: int
    inserted: List[Dict[str, Any]] = []
    parsed_rows: List[Dict[str, Any]] = []

@router.post("/scan-pdf", response_model=ScanResponse)
async def scan_pdf_endpoint(pdf: UploadFile = File(...)):
    """
    Handles direct upload of a single curriculum PDF.
    Uses the same logic as orchestrator.ingest_courses_from_pdf().
    """
    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    try:
        file_bytes = await pdf.read()

        # Run in a thread (since scan_pdf_and_store might be heavy/blocking)
        result = await asyncio.to_thread(scan_pdf_and_store, file_bytes)

        # Build a consistent response
        return ScanResponse(
            inserted_count=len(result.get("inserted", []) or []),
            parsed_count=len(result.get("parsed_rows", []) or []),
            raw_text_len=int(result.get("raw_text_len", 0)),
            inserted=result.get("inserted", []) or [],
            parsed_rows=result.get("parsed_rows", []) or [],
        )

    except Exception as e:
        logger.exception("❌ scan_pdf failed")
        raise HTTPException(status_code=500, detail=f"PDF scan failed: {e}")
