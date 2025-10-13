# backend/app/services/orchestrator.py
from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, Optional, Iterable, List, Union
from pathlib import Path
import asyncio
import glob

from dotenv import load_dotenv

# load variables from .env early so everything below can read them
load_dotenv()

# set up logging so we can see what's happening while the pipeline runs
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [orchestrator.service] %(message)s",
)

# pipeline steps
from .scraper import scrape_jobs_from_google_jobs
from .skill_extractor import extract_skills_from_jobs
from .syllabus_matcher import extract_subject_skills_from_supabase
from .evaluator import compute_subject_scores_and_save
from .pdf_report import generate_pdf_report, fetch_clean_report_data
from ..ml.train_model import train_subject_score_model
from ..ml.train_query_model import train_query_model
from ..core.supabase_client import insert_job
from ..core.supabase_client import supabase  # used for DB guards

# NEW: trending jobs computation (runs after we insert jobs)
from .trending_jobs import compute_trending_jobs

# Final checking (kept available for callers that need it)
from .final_checking import run_final_checks

# NEW: storage upload helper (Supabase Storage, signed/public URL)
from .storage_utils import upload_pdf_to_supabase_storage

# NEW: curriculum PDF → COURSES upsert (major-only parser)
from .scan_pdf import scan_pdf_and_store


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


async def _yield_now():
    await asyncio.sleep(0)


def _chunks(iterable: Iterable[Any], size: int) -> Iterable[List[Any]]:
    batch: List[Any] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


# ----------------------------------------------------------------------
# Scraping + ingest (+ trending update)
# ----------------------------------------------------------------------
async def scrape_and_ingest(scrape_enabled: bool) -> Dict[str, Any]:
    """
    1) Scrape jobs (SerpAPI → Google Jobs)
    2) Insert them into Supabase in batches
    3) (NEW) Recompute trending jobs if UPDATE_TRENDING is enabled
    4) Return some stats (counts + timing)
    """
    logging.debug("Entering scrape_and_ingest function.")
    results: Dict[str, Any] = {"scraped_jobs": 0, "inserted_jobs": 0, "errors": []}

    if not scrape_enabled:
        logging.info("Skipping scrape step (scrape_enabled=False).")
        logging.debug("Exiting scrape_and_ingest function early.")
        return results

    t0 = time.perf_counter()
    try:
        logging.info("🌐 Scraping job listings from Google Jobs via SerpApi…")
        logging.debug("Calling scrape_jobs_from_google_jobs (offloaded to thread)...")

        all_jobs = await asyncio.to_thread(scrape_jobs_from_google_jobs)
        results["scraped_jobs"] = len(all_jobs) if all_jobs else 0
        logging.debug(
            "scrape_jobs_from_google_jobs completed. Found %d jobs.",
            results["scraped_jobs"],
        )

        await _yield_now()

        if not all_jobs:
            logging.warning("No new jobs scraped. Proceeding with existing job data in Supabase.")
        else:
            inserted = 0
            BATCH_SIZE = 50

            logging.debug(
                "Attempting to insert %d jobs (batch size: %d).",
                results["scraped_jobs"],
                BATCH_SIZE,
            )

            for batch in _chunks(all_jobs, BATCH_SIZE):
                for job in batch:
                    try:
                        await asyncio.to_thread(insert_job, job)
                        inserted += 1
                    except Exception as e:
                        title = (job or {}).get("title", "unknown")
                        msg = f"Failed to insert job '{title}': {e}"
                        logging.exception(msg)
                        results["errors"].append(msg)

                logging.debug(
                    "Inserted %d/%d so far…", inserted, results["scraped_jobs"]
                )
                await _yield_now()

            results["inserted_jobs"] = inserted
            logging.info(
                "Inserted %d/%d scraped jobs into Supabase.",
                inserted,
                results["scraped_jobs"],
            )

        # --------------- NEW: Trending jobs recompute ---------------
        update_trending = _env_flag("UPDATE_TRENDING", True)
        if update_trending:
            try:
                logging.info("📈 Updating trending jobs…")
                # compute_trending_jobs is sync; run it off the event loop
                await asyncio.to_thread(compute_trending_jobs)
                logging.info("✅ Trending jobs updated.")
            except Exception as te:
                logging.warning("⚠️ compute_trending_jobs failed: %r", te, exc_info=True)
        else:
            logging.info("Skipping trending jobs update (UPDATE_TRENDING is disabled).")
        # ------------------------------------------------------------

    except Exception as e:
        msg = f"Scrape/ingest step failed: {e}"
        logging.exception(msg)
        results["errors"].append(msg)
        raise
    finally:
        results["timing_sec"] = round(time.perf_counter() - t0, 3)
        logging.debug(
            "Exiting scrape_and_ingest function. Took %s seconds.",
            results["timing_sec"],
        )
    return results


# ----------------------------------------------------------------------
# NEW: Curriculum PDF → COURSES upsert (uses MAJOR COURSE DESCRIPTION(S) only)
# ----------------------------------------------------------------------
async def ingest_courses_from_pdf(pdf: Union[str, Path, bytes]) -> Dict[str, Any]:
    """
    Parse a single curriculum PDF and upsert courses (STRICTLY the
    'MAJOR COURSE DESCRIPTION(S)' section), then return a summary.

    Args:
      pdf: path-like or raw bytes

    Returns: {
      "inserted_count": int,
      "parsed_count": int,
      "raw_text_len": int,
      "inserted": [...],
      "parsed_rows": [...]
    }
    """
    logging.debug("Entering ingest_courses_from_pdf.")
    t0 = time.perf_counter()

    try:
        # Load bytes
        if isinstance(pdf, (str, Path)):
            pdf_path = Path(pdf)
            if not pdf_path.exists():
                raise FileNotFoundError(f"PDF not found: {pdf_path}")
            logging.info("📚 Parsing curriculum PDF: %s", pdf_path)
            file_bytes = pdf_path.read_bytes()
        elif isinstance(pdf, (bytes, bytearray)):
            logging.info("📚 Parsing curriculum PDF from memory bytes.")
            file_bytes = bytes(pdf)
        else:
            raise TypeError("pdf must be a path-like or bytes")

        # Parse + upsert (major-only) off the event loop
        result = await asyncio.to_thread(scan_pdf_and_store, file_bytes)

        inserted = result.get("inserted", []) or []
        parsed_rows = result.get("parsed_rows", []) or []
        summary = {
            "inserted_count": len(inserted),
            "parsed_count": len(parsed_rows),
            "raw_text_len": int(result.get("raw_text_len", 0)),
            "inserted": inserted,
            "parsed_rows": parsed_rows,
        }

        logging.info(
            "✅ Curriculum ingest complete. parsed=%d inserted=%d raw_text_len=%d",
            summary["parsed_count"], summary["inserted_count"], summary["raw_text_len"]
        )
        return summary

    except Exception as e:
        msg = f"Curriculum ingest failed: {e}"
        logging.exception(msg)
        raise
    finally:
        elapsed = round(time.perf_counter() - t0, 3)
        logging.info("Curriculum ingest timing: %s sec", elapsed)


async def ingest_courses_from_pdf_paths(paths: List[str]) -> Dict[str, Any]:
    """
    Convenience wrapper to ingest multiple PDFs and aggregate results.
    Accepts globs as well (e.g., ['data/*.pdf', 'more/file.pdf'])
    """
    logging.debug("Entering ingest_courses_from_pdf_paths.")
    t0 = time.perf_counter()

    try:
        # Expand globs
        expanded: List[Path] = []
        for p in paths:
            matches = [Path(m) for m in glob.glob(p)]
            if not matches and Path(p).exists():
                matches = [Path(p)]
            expanded.extend(matches)

        if not expanded:
            logging.warning("No PDFs matched: %s", paths)

        agg = {
            "files": [str(p) for p in expanded],
            "total_parsed": 0,
            "total_inserted": 0,
            "details": [],
        }

        for pdf_path in expanded:
            try:
                res = await ingest_courses_from_pdf(pdf_path)
                agg["details"].append({"file": str(pdf_path), **res})
                agg["total_parsed"] += res.get("parsed_count", 0)
                agg["total_inserted"] += res.get("inserted_count", 0)
            except Exception as e:
                logging.exception("Failed ingest for %s: %s", pdf_path, e)
            await _yield_now()

        logging.info(
            "📚 Batch curriculum ingest complete. files=%d parsed=%d inserted=%d",
            len(expanded), agg["total_parsed"], agg["total_inserted"]
        )
        return agg

    finally:
        elapsed = round(time.perf_counter() - t0, 3)
        logging.info("Batch curriculum ingest timing: %s sec", elapsed)


# ----------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------
async def extract_skills(extract_enabled: bool, use_stored_data: bool) -> None:
    """
    Extract skills from jobs and from courses.

    Behavior:
    - ALWAYS run `extract_subject_skills_from_supabase()` which reads the **courses**
      table and (re)writes into **course_skills**.
    - `use_stored_data` only indicates the run originates from existing DB state
      (not PDF upload); it does NOT suppress creation of course_skills anymore.
    """
    logging.debug("Entering extract_skills function.")
    if not extract_enabled:
        logging.info("Skipping extraction step (extract_enabled=False).")
        logging.debug("Exiting extract_skills function early.")
        return

    t0 = time.perf_counter()
    try:
        # ---- Job skills (always try)
        logging.info("🧠 Extracting skills from job descriptions…")
        await asyncio.to_thread(extract_skills_from_jobs)
        logging.debug("extract_skills_from_jobs completed.")
        await _yield_now()

        # ---- Course skills (ALWAYS run, source is courses table)
        logging.info("📘 Extracting course/subject skills from *courses* table…")
        await asyncio.to_thread(extract_subject_skills_from_supabase)
        logging.debug("extract_subject_skills_from_supabase completed.")
        await _yield_now()

    except Exception as e:
        msg = f"Skill extraction step failed: {e}"
        logging.exception(msg)
        raise
    finally:
        elapsed = round(time.perf_counter() - t0, 3)
        logging.info("Extraction timing: %s sec", elapsed)


# ----------------------------------------------------------------------
# Retrain models
# ----------------------------------------------------------------------
async def retrain_ml_models(retrain: bool) -> None:
    logging.debug("Entering retrain_ml_models function.")
    if not retrain:
        logging.info("Skipping model retraining (retrain=False).")
        logging.debug("Exiting retrain_ml_models function early.")
        return

    t0 = time.perf_counter()
    try:
        logging.info("🤖 Retraining ML models…")
        await asyncio.to_thread(train_subject_score_model)
        logging.debug("train_subject_score_model completed.")
        await _yield_now()

        await asyncio.to_thread(train_query_model)
        logging.debug("train_query_model completed.")
        await _yield_now()

        logging.info("Model retraining completed.")
    except Exception as e:
        msg = f"Model retraining failed: {e}"
        logging.exception(msg)
        raise
    finally:
        elapsed = round(time.perf_counter() - t0, 3)
        logging.info("Retraining timing: %s sec", elapsed)


# ----------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------
async def evaluate_and_save_scores() -> Optional[Dict[str, Any]]:
    """
    Runs the evaluation step which writes to the DB. Some implementations
    may return a report-like structure; others return None and rely on DB reads.

    Guard: if `course_skills` has no rows, skip evaluation to avoid
    writing spurious scores when there is nothing to score.
    """
    logging.debug("Entering evaluate_and_save_scores function.")
    t0 = time.perf_counter()
    report: Optional[Dict[str, Any]] = None
    try:
        # Check availability of course_skills WITHOUT HEAD
        try:
            resp = (
                supabase.table("course_skills")
                .select("course_skll_id", count="exact")
                .range(0, 0)  # triggers count with minimal payload
                .execute()
            )
            course_skill_rows = int(getattr(resp, "count", 0) or 0)
        except Exception as e:
            logging.warning(
                "Could not check course_skills count before evaluation: %r", e
            )
            course_skill_rows = 0

        if course_skill_rows == 0:
            logging.info("⛔ No course_skills available; skipping evaluation step.")
            return None

        logging.info("📊 Computing subject success scores…")
        report = await asyncio.to_thread(compute_subject_scores_and_save)
        logging.debug("compute_subject_scores_and_save completed.")
        await _yield_now()

        logging.info("Subject success scores computed and saved.")
        return report
    except Exception as e:
        msg = f"Scoring/evaluation failed: {e}"
        logging.exception(msg)
        raise
    finally:
        elapsed = round(time.perf_counter() - t0, 3)
        logging.info("Evaluation timing: %s sec", elapsed)


# ----------------------------------------------------------------------
# Validation (exposed helper)
# ----------------------------------------------------------------------
async def validate_after_evaluation(
    report_data: Optional[Dict[str, Any] | List[Dict[str, Any]]],
    *,
    strict: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Helper for callers that want to validate raw report data in-process.
    Returns the same structure as run_final_checks (i.e., {"rows": [...]})
    """
    logging.info("🔎 Running final checks on evaluated results…")
    validated = await run_final_checks(report_data, strict=strict)
    logging.info(
        "✅ Final checks passed. %d rows ready for PDF.", len(validated.get("rows", []))
    )
    return validated


# ----------------------------------------------------------------------
# PDF Generation (uploads to Supabase Storage; falls back to static URL)
# ----------------------------------------------------------------------
async def generate_and_store_pdf_report(
    gen_pdf: bool,
    report_data: Optional[Dict[str, Any] | List[Dict[str, Any]]],
) -> Optional[Dict[str, str]]:
    """
    Generate the PDF report.
    IMPORTANT: This function **does not** re-run final checks. It expects either:
      - a dict with {"rows": [...]} that has already been validated, or
      - a plain list[dict] of rows ready for PDF, or
      - None, in which case it will load the latest cleaned rows from the DB.
    After rendering, it **uploads** the PDF to Supabase Storage and returns a durable URL
    (signed by default). If the upload fails, it falls back to the static URL path.
    """
    logging.debug("Entering generate_and_store_pdf_report function.")
    if not gen_pdf:
        logging.info("Skipping PDF generation (gen_pdf=False).")
        return None

    t0 = time.perf_counter()
    pdf_path: Optional[str] = None
    try:
        logging.info("📝 Generating PDF report…")

        # ---- Normalize input to a list of rows (no double-validation) ----
        if isinstance(report_data, dict) and "rows" in report_data:
            rows: List[Dict[str, Any]] = report_data["rows"]  # already validated by caller
            logging.info("PDF input type: dict; rows=%d", len(rows))
        elif isinstance(report_data, list):
            rows = report_data  # assume caller passed rows directly
            logging.info("PDF input type: list; rows=%d", len(rows))
        else:
            logging.warning(
                "No in-memory report data; fetching latest cleaned results for PDF."
            )
            rows = await asyncio.to_thread(fetch_clean_report_data)  # already-clean table
            logging.info("PDF input type: fetched; rows=%d", len(rows))

        if not rows:
            raise RuntimeError("No report data available to generate PDF.")

        logging.info("PDF rows to render: %d", len(rows))

        # Render PDF from rows (returns ABSOLUTE path; pdf_report verifies existence/size)
        pdf_path = await asyncio.to_thread(generate_pdf_report, rows)
        logging.info("PDF report generated at: %s", pdf_path)
        await _yield_now()

        # Extra safety: verify again here (defensive check)
        try:
            p = Path(pdf_path) if pdf_path else None
            exists = p.exists() if p else False
            size = p.stat().st_size if exists else 0
            logging.info("PDF path check: exists=%s size=%s", exists, size)
            if not exists or size <= 0:
                raise RuntimeError(f"PDF not found or empty at {pdf_path}")
        except Exception as ve:
            logging.exception("PDF verification failed: %s", ve)
            raise

        # Optional convenience copy to local Downloads (best-effort)
        try:
            downloads_dir = Path.home() / "Downloads"
            downloads_dir.mkdir(exist_ok=True)
            dest_path = downloads_dir / Path(pdf_path).name  # type: ignore[arg-type]
            if Path(pdf_path).resolve() != dest_path.resolve():  # type: ignore[arg-type]
                from shutil import copyfile
                await asyncio.to_thread(copyfile, pdf_path, dest_path)  # type: ignore[arg-type]
            logging.info("📥 PDF also copied to: %s", dest_path)
        except Exception as e:
            logging.warning("Could not copy PDF to Downloads: %s", e)

        # ---------------- NEW: Upload to Supabase Storage ----------------
        report_url: Optional[str] = None
        try:
            # Prefer private bucket + signed URL
            report_url = await asyncio.to_thread(
                upload_pdf_to_supabase_storage,
                pdf_path,          # local absolute path
                False,             # make_public=False (use signed URL)
                # signed_seconds=3600,  # uncomment to override default expiry (e.g., 1 hour)
            )
            logging.info("☁️ Uploaded PDF to Supabase Storage: %s", report_url)
        except Exception as e:
            logging.error("❌ Failed to upload PDF to Supabase Storage: %s", e)
            # --------- Fallback: local static URL (if you still serve /static) ----------
            try:
                base_url = os.getenv("PUBLIC_BASE_URL", "https://curricalign-production.up.railway.app").rstrip("/")
                static_prefix = os.getenv("STATIC_URL_PREFIX", "/static").rstrip("/")
                filename = Path(pdf_path).name if pdf_path else None
                fallback_url = f"{base_url}{static_prefix}/reports/{filename}" if filename else None
                logging.info("Using fallback static URL: %s", fallback_url)
                report_url = fallback_url
            except Exception as fe:
                logging.error("Failed building fallback static URL: %s", fe)
                report_url = None
        # ----------------------------------------------------------------

        return {"path": pdf_path, "url": report_url}

    except Exception as e:
        msg = f"PDF generation failed: {e}"
        logging.exception(msg)
        raise
    finally:
        elapsed = round(time.perf_counter() - t0, 3)
        logging.info("PDF generation timing: %s sec", elapsed)
