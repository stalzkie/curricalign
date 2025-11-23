# apps/backend/api/endpoints/scan_csv.py
from __future__ import annotations

import logging
import asyncio
import tempfile
import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any

# import the new CSV scanner
from ...services.scan_pdf import scan_csv_and_store  # Replace scan_pdf with scan_csv module if renamed

router = APIRouter()
logger = logging.getLogger(__name__)

# Response model aligned with CSV output
class ScanResponse(BaseModel):
    inserted_count: int
    parsed_count: int
    inserted: List[Dict[str, Any]] = []
    parsed_rows: List[Dict[str, Any]] = []

@router.post("/scan-pdf", response_model=ScanResponse)
async def scan_csv_endpoint(csv_file: UploadFile = File(...)):
    """
    Handles direct upload of the CSV-based curriculum file.
    Expects a CSV containing: course_code, course_title, course_description.
    """

    # 1. Validate extension
    if not csv_file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    try:
        # 2. Read bytes
        file_bytes = await csv_file.read()

        # 3. Save to a temporary CSV file for scan_csv_and_store()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        # 4. Execute scanner in a thread (safe for blocking CPU/file I/O)
        try:
            result = await asyncio.to_thread(scan_csv_and_store, tmp_path)
        finally:
            # Clean up temporary file
            os.remove(tmp_path)

        # 5. Build clean frontend response
        return ScanResponse(
            inserted_count=int(result.get("total_inserted", 0)),
            parsed_count=int(result.get("total_parsed", 0)),
            inserted=result.get("inserted_rows", []) or [],
            parsed_rows=result.get("parsed_rows", []) or [],
        )

    except Exception as e:
        logger.exception("❌ scan_csv failed")
        raise HTTPException(status_code=500, detail=f"CSV scan failed: {e}")
