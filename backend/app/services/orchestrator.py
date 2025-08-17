# backend/app/services/orchestrator.py
from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, Optional, Iterable
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

# import all the pipeline steps (they are mostly sync, so we'll run them in threads)
from .scraper import scrape_jobs_from_google_jobs
from .skill_extractor import extract_skills_from_jobs
from .syllabus_matcher import extract_subject_skills_from_supabase
from .evaluator import compute_subject_scores_and_save
from .pdf_report import generate_pdf_report, fetch_report_data_from_supabase
from ..ml.train_model import train_subject_score_model
from ..ml.train_query_model import train_query_model
from ..core.supabase_client import insert_job


def _env_flag(name: str, default: bool) -> bool:
    """
    Read a boolean flag from environment variables.
    Accepts: 1/true/yes/on (case-insensitive) as True.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


async def _yield_now():
    """
    Tiny pause so the event loop can send Server-Sent-Events (SSE) to the frontend.
    This keeps the UI feeling responsive.
    """
    await asyncio.sleep(0)


def _chunks(iterable: Iterable[Any], size: int) -> Iterable[list[Any]]:
    """
    Split an iterable into small lists (batches) of length <= size.
    Useful so big inserts don't block the loop for too long.
    """
    batch: list[Any] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


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

        # run the blocking scraper in a thread so we don't block the event loop
        all_jobs = await asyncio.to_thread(scrape_jobs_from_google_jobs)
        results["scraped_jobs"] = len(all_jobs) if all_jobs else 0
        logging.debug(
            "scrape_jobs_from_google_jobs completed. Found %d jobs.",
            results["scraped_jobs"],
        )

        # let SSE frames flush
        await _yield_now()

        if not all_jobs:
            logging.warning("No new jobs scraped. Proceeding with existing job data in Supabase.")
        else:
            inserted = 0
            BATCH_SIZE = 50  # small batches to keep things snappy

            logging.debug(
                "Attempting to insert %d jobs (batch size: %d).",
                results["scraped_jobs"],
                BATCH_SIZE,
            )

            for batch in _chunks(all_jobs, BATCH_SIZE):
                # insert each job in a worker thread
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
                await _yield_now()  # keep the stream alive

            results["inserted_jobs"] = inserted
            logging.info(
                "Inserted %d/%d scraped jobs into Supabase.",
                inserted,
                results["scraped_jobs"],
            )

    except Exception as e:
        msg = f"Scrape/ingest step failed: {e}"
        logging.exception(msg)
        results["errors"].append(msg)
        # raise so the orchestrator endpoint can handle/report it
        raise
    finally:
        results["timing_sec"] = round(time.perf_counter() - t0, 3)
        logging.debug(
            "Exiting scrape_and_ingest function. Took %s seconds.",
            results["timing_sec"],
        )
    return results


async def extract_skills(extract_enabled: bool, use_stored_data: bool) -> None:
    """
    Extract skills from:
      - job descriptions (always if enabled)
      - course PDFs/DB (only if not using stored data)
    """
    logging.debug("Entering extract_skills function.")
    if not extract_enabled:
        logging.info("Skipping extraction step (extract_enabled=False).")
        logging.debug("Exiting extract_skills function early.")
        return

    t0 = time.perf_counter()
    try:
        logging.info("🧠 Extracting skills from job descriptions…")
        logging.debug("Calling extract_skills_from_jobs (offloaded to thread)...")

        # run synchronous extractor on a worker thread
        await asyncio.to_thread(extract_skills_from_jobs)
        logging.debug("extract_skills_from_jobs completed.")

        await _yield_now()

        if not use_stored_data:
            logging.info("📘 Extracting course/subject skills from PDF/DB…")
            logging.debug(
                "Calling extract_subject_skills_from_supabase (offloaded to thread)..."
            )
            await asyncio.to_thread(extract_subject_skills_from_supabase)
            logging.debug("extract_subject_skills_from_supabase completed.")
            await _yield_now()
        else:
            logging.info("Skipping subject skill extraction (use_stored_data=True). Using existing course skills in DB.")

    except Exception as e:
        msg = f"Skill extraction step failed: {e}"
        logging.exception(msg)
        raise
    finally:
        elapsed = round(time.perf_counter() - t0, 3)
        logging.info("Extraction timing: %s sec", elapsed)
        logging.debug("Exiting extract_skills function. Took %s seconds.", elapsed)


async def retrain_ml_models(retrain: bool) -> None:
    """
    Retrain ML models when the flag is True.
    This can take time, so we run each trainer in a thread.
    """
    logging.debug("Entering retrain_ml_models function.")
    if not retrain:
        logging.info("Skipping model retraining (retrain=False).")
        logging.debug("Exiting retrain_ml_models function early.")
        return

    t0 = time.perf_counter()
    try:
        logging.info("🤖 Retraining ML models…")
        logging.debug("Calling train_subject_score_model (offloaded to thread)...")
        await asyncio.to_thread(train_subject_score_model)
        logging.debug("train_subject_score_model completed.")
        await _yield_now()

        logging.debug("Calling train_query_model (offloaded to thread)...")
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
        logging.debug("Exiting retrain_ml_models function. Took %s seconds.", elapsed)


async def evaluate_and_save_scores() -> Optional[Dict[str, Any]]:
    """
    Run the evaluator:
      - compute course alignment scores
      - save them to Supabase
      - return any report data the evaluator gives back (if any)
    """
    logging.debug("Entering evaluate_and_save_scores function.")
    t0 = time.perf_counter()
    report: Optional[Dict[str, Any]] = None
    try:
        logging.info("📊 Computing subject success scores…")
        logging.debug("Calling compute_subject_scores_and_save (offloaded to thread)...")

        # compute + save in a background thread
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
        logging.debug("Exiting evaluate_and_save_scores function. Took %s seconds.", elapsed)


async def generate_and_store_pdf_report(
    gen_pdf: bool, report_data: Optional[Dict[str, Any]]
) -> Optional[Dict[str, str]]:
    """
    Generate the PDF report and return paths:
      { "path": "/abs/path/to/file.pdf", "url": "http://.../reports/file.pdf" }
    If gen_pdf is False, we skip this step.
    """
    logging.debug("Entering generate_and_store_pdf_report function.")
    if not gen_pdf:
        logging.info("Skipping PDF generation (gen_pdf=False).")
        logging.debug("Exiting generate_and_store_pdf_report function early.")
        return None

    t0 = time.perf_counter()
    pdf_path: Optional[str] = None
    try:
        logging.info("📝 Generating PDF report…")

        # use already-computed data if available, else fetch from DB
        data_for_pdf = report_data
        if not data_for_pdf:
            logging.warning("No in-memory report data; fetching latest from Supabase for PDF.")
            logging.debug("Calling fetch_report_data_from_supabase (offloaded to thread)...")
            data_for_pdf = await asyncio.to_thread(fetch_report_data_from_supabase)
            logging.debug("fetch_report_data_from_supabase completed.")
            await _yield_now()

        if not data_for_pdf:
            raise RuntimeError("No report data available to generate PDF.")

        logging.debug("Calling generate_pdf_report (offloaded to thread)...")
        pdf_path = await asyncio.to_thread(generate_pdf_report, data_for_pdf)
        logging.debug("generate_pdf_report completed. PDF path: %s", pdf_path)
        await _yield_now()

        logging.info("PDF report generated at: %s", pdf_path)

        # (nice-to-have) also copy the PDF to user's Downloads folder
        try:
            downloads_dir = Path.home() / "Downloads"
            downloads_dir.mkdir(exist_ok=True)
            dest_path = downloads_dir / Path(pdf_path).name  # type: ignore[arg-type]
            if Path(pdf_path).resolve() != dest_path.resolve():  # type: ignore[arg-type]
                from shutil import copyfile
                await asyncio.to_thread(copyfile, pdf_path, dest_path)  # type: ignore[arg-type]
            logging.info("📥 PDF also copied to: %s", dest_path)
        except Exception as e:
            # not critical — we just warn and continue
            logging.warning("Could not copy PDF to Downloads: %s", e)

        # build a public URL so the frontend can open/download it
        base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
        filename = Path(pdf_path).name if pdf_path else None
        report_url = f"{base_url}/app/static/reports/{filename}" if filename else None

        return {"path": pdf_path, "url": report_url}

    except Exception as e:
        msg = f"PDF generation failed: {e}"
        logging.exception(msg)
        raise
    finally:
        elapsed = round(time.perf_counter() - t0, 3)
        logging.info("PDF generation timing: %s sec", elapsed)
        logging.debug(
            "Exiting generate_and_store_pdf_report function. Took %s seconds.",
            elapsed,
        )
