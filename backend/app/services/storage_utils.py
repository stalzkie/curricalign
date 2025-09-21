# backend/app/services/storage_utils.py
from supabase import create_client
import os
from pathlib import Path

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
BUCKET = os.getenv("SUPABASE_BUCKET", "reports")  # e.g. "reports"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def upload_pdf_to_supabase_storage(
    file_path: str,
    make_public: bool = False,
    signed_seconds: int = 3600,
) -> str:
    """Upload a PDF to Supabase Storage and return a public or signed URL."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"{file_path} not found")

    dest_name = f"reports/{path.name}"

    # Upload (overwrites if exists)
    with open(path, "rb") as f:
        supabase.storage.from_(BUCKET).upload(dest_name, f, {"upsert": "true"})

    if make_public:
        return supabase.storage.from_(BUCKET).get_public_url(dest_name)
    else:
        return supabase.storage.from_(BUCKET).create_signed_url(dest_name, signed_seconds)["signedURL"]
