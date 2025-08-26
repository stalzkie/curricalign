# backend/app/services/orchestrator.py
from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, Optional, Iterable, List
from pathlib import Path
import asyncio

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

# Final checking (kept available for callers that need it)
from .final_checking import run_final_checks


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


async def _yield_now():
    await asyncio.sleep(0)


def _chunks(iterable: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


# ----------------------------------------------------------------------
# Scraping + ingest
# ----------------------------------------------------------------------
async def scrape_and_ingest(scrape_enabled: bool) -> Dict[str, Any]:
    """
    1) Scrape jobs (SerpAPI → Google Jobs)
    2) Insert them into Supabase in batches
    3) Return some stats (counts + timing)
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
        logging.debug("scrape_jobs_from_google_jobs completed. Found %d jobs.", results["scraped_jobs"])

        await _yield_now()

        if not all_jobs:
            logging.warning("No new jobs scraped. Proceeding with existing job data in Supabase.")
        else:
            inserted = 0
            BATCH_SIZE = 50

            logging.debug("Attempting to insert %d jobs (batch size: %d).", results["scraped_jobs"], BATCH_SIZE)

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

                logging.debug("Inserted %d/%d so far…", inserted, results["scraped_jobs"])
                await _yield_now()

            results["inserted_jobs"] = inserted
            logging.info("Inserted %d/%d scraped jobs into Supabase.", inserted, results["scraped_jobs"])

    except Exception as e:
        msg = f"Scrape/ingest step failed: {e}"
        logging.exception(msg)
        results["errors"].append(msg)
        raise
    finally:
        results["timing_sec"] = round(time.perf_counter() - t0, 3)
        logging.debug("Exiting scrape_and_ingest function. Took %s seconds.", results["timing_sec"])
    return results


# ----------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------
async def extract_skills(extract_enabled: bool, use_stored_data: bool) -> None:
    logging.debug("Entering extract_skills function.")
    if not extract_enabled:
        logging.info("Skipping extraction step (extract_enabled=False).")
        logging.debug("Exiting extract_skills function early.")
        return

    t0 = time.perf_counter()
    try:
        logging.info("🧠 Extracting skills from job descriptions…")
        await asyncio.to_thread(extract_skills_from_jobs)
        logging.debug("extract_skills_from_jobs completed.")
        await _yield_now()

        if not use_stored_data:
            logging.info("📘 Extracting course/subject skills from PDF/DB…")
            await asyncio.to_thread(extract_subject_skills_from_supabase)
            logging.debug("extract_subject_skills_from_supabase completed.")
            await _yield_now()
        else:
            logging.info("Skipping subject skill extraction (use_stored_data=True).")

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
    """
    logging.debug("Entering evaluate_and_save_scores function.")
    t0 = time.perf_counter()
    report: Optional[Dict[str, Any]] = None
    try:
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
    logging.info("✅ Final checks passed. %d rows ready for PDF.", len(validated.get("rows", [])))
    return validated


# ----------------------------------------------------------------------
# PDF Generation
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
            logging.debug("Received validated dict with %d rows for PDF.", len(rows))
        elif isinstance(report_data, list):
            rows = report_data  # assume caller passed rows directly
            logging.debug("Received list with %d rows for PDF.", len(rows))
        else:
            logging.warning("No in-memory report data; fetching latest cleaned results for PDF.")
            rows = await asyncio.to_thread(fetch_clean_report_data)  # already-clean table

        if not rows:
            raise RuntimeError("No report data available to generate PDF.")

        # Render PDF from rows
        pdf_path = await asyncio.to_thread(generate_pdf_report, rows)
        logging.info("PDF report generated at: %s", pdf_path)
        await _yield_now()

        # Copy to Downloads for convenience (best-effort)
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

        # Build a public URL (served by your static route)
        base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
        static_prefix = os.getenv("STATIC_URL_PREFIX", "/static").rstrip("/")
        filename = Path(pdf_path).name if pdf_path else None
        report_url = f"{base_url}{static_prefix}/reports/{filename}" if filename else None

        return {"path": pdf_path, "url": report_url}

    except Exception as e:
        msg = f"PDF generation failed: {e}"
        logging.exception(msg)
        raise
    finally:
        elapsed = round(time.perf_counter() - t0, 3)
        logging.info("PDF generation timing: %s sec", elapsed)
