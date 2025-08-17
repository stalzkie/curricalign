# backend/app/api/endpoints/report_files.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path, PurePath

router = APIRouter()

# Always resolve an absolute path to the reports folder:
# <repo-root>/backend/static/reports
REPORTS_DIR = (Path(__file__).resolve().parents[3] / "backend" / "static" / "reports").resolve()
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

@router.get("/reports/{filename}")
def download_report(filename: str):
    # Only allow a plain filename (no traversal)
    if ("/" in filename) or ("\\" in filename) or (PurePath(filename).name != filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = (REPORTS_DIR / filename).resolve()
    # Ensure the resolved path still sits under REPORTS_DIR
    if not str(file_path).startswith(str(REPORTS_DIR)):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not file_path.exists() or file_path.is_dir():
        raise HTTPException(status_code=404, detail="Report not found")

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=filename,  # forces Content-Disposition: attachment
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
