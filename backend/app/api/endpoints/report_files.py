# backend/app/api/endpoints/report_files.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path, PurePath

router = APIRouter(prefix="/reports", tags=["reports"])

# This file is backend/app/api/endpoints/report_files.py
# parents[2] == backend/app   ✅
REPORTS_DIR = (Path(__file__).resolve().parents[3] / "static" / "reports").resolve()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
print(f"[reports] Serving from: {REPORTS_DIR}")  # <- keep for one run

@router.get("/{filename}")
def download_report(filename: str):
    if ("/" in filename) or ("\\" in filename) or (PurePath(filename).name != filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = (REPORTS_DIR / filename).resolve()
    if not str(file_path).startswith(str(REPORTS_DIR)):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not file_path.exists() or file_path.is_dir():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(str(file_path), media_type="application/pdf", filename=filename,
                        headers={"Cache-Control": "no-store","X-Content-Type-Options":"nosniff"})

# (Optional) so your HEAD probes don’t 405:
@router.head("/{filename}")
def head_report(filename: str):
    if ("/" in filename) or ("\\" in filename) or (PurePath(filename).name != filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = (REPORTS_DIR / filename).resolve()
    if not str(file_path).startswith(str(REPORTS_DIR)):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not file_path.exists() or file_path.is_dir():
        raise HTTPException(status_code=404, detail="Report not found")
    return {}
