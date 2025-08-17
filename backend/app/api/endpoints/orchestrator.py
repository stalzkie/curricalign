# backend/app/api/endpoints/orchestrator.py
from __future__ import annotations

import os
import json
import traceback
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import logging

from fastapi import APIRouter, BackgroundTasks, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from ...core.event_bus import publish, subscribe, unsubscribe, get_status
from ...services import orchestrator as pipeline_service

router = APIRouter()

_last_report_url: Dict[str, str] = {}
cancelled_jobs: set[str] = set()


def _ts() -> str:
    """Returns the current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _apply_optional_env_flags(payload: Dict[str, Any]) -> None:
    """Applies environment flags based on the payload."""
    if "scrapeEnabled" in payload:
        os.environ["SCRAPE_ENABLED"] = "true" if payload["scrapeEnabled"] else "false"
    if "extractEnabled" in payload:
        os.environ["EXTRACT_ENABLED"] = "true" if payload["extractEnabled"] else "false"
    if "retrainModels" in payload:
        os.environ["RETRAIN_MODELS"] = "true" if payload["retrainModels"] else "false"
    if "generatePdf" in payload:
        os.environ["GENERATE_PDF"] = "true" if payload["generatePdf"] else "false"


def _emit(job_id: str, fn: str, status: str, report_url: Optional[str] = None) -> None:
    """Publishes an event to the job's event bus."""
    event: Dict[str, Any] = {"function": fn, "status": status, "timestamp": _ts()}
    if report_url:
        event["reportUrl"] = report_url
        _last_report_url[job_id] = report_url
    logging.info(
        f"[_emit] Preparing to publish: Job={job_id}, Function={fn}, Status={status}, "
        f"ReportUrl={report_url or 'N/A'}"
    )
    publish(job_id, event)


async def _yield_now() -> None:
    """Micro-yield so the event loop can flush SSE frames."""
    await asyncio.sleep(0)


async def _background_job(job_id: str, payload: Dict[str, Any]) -> None:
    """
    Runs the pipeline asynchronously and emits step-by-step events that match the frontend.
    'source' semantics:
      - "pdf": frontend uploaded a PDF (subject extraction will read newly uploaded content)
      - "stored": NO new PDF upload; still scrape jobs, extract job skills, evaluate, and generate PDF
    """
    logging.info(f"[Background Job] Started for jobId: {job_id} with payload: {payload}")
    source = str(payload.get("source", "fresh")).lower()
    use_stored_data = (source == "stored")
    retrain_models_flag = payload.get("retrainModels", False)  # default False
    generate_pdf_flag = payload.get("generatePdf", True)       # default True

    _apply_optional_env_flags(payload)

    scrape_enabled = os.getenv("SCRAPE_ENABLED", "true").lower() == "true"
    extract_enabled = os.getenv("EXTRACT_ENABLED", "true").lower() == "true"
    retrain_models = os.getenv("RETRAIN_MODELS", "false").lower() == "true" or retrain_models_flag
    generate_pdf = os.getenv("GENERATE_PDF", "true").lower() == "true" or generate_pdf_flag

    logging.debug(
        f"[Background Job] Effective flags: Scrape={scrape_enabled}, "
        f"Extract={extract_enabled}, Retrain={retrain_models}, PDF={generate_pdf}"
    )

    try:
        # SCRAPE & INGEST JOBS
        if job_id in cancelled_jobs:
            logging.info(f"[Background Job] Job {job_id} cancelled during scrape phase.")
            _emit(job_id, "scrape_jobs_from_google_jobs", "cancelled")
            await _yield_now()
            return

        _emit(job_id, "scrape_jobs_from_google_jobs", "started")
        await _yield_now()

        logging.debug(f"[Background Job] Calling pipeline_service.scrape_and_ingest for job {job_id}...")
        _ = await pipeline_service.scrape_and_ingest(scrape_enabled=scrape_enabled)

        _emit(job_id, "scrape_jobs_from_google_jobs", "completed")
        await _yield_now()
        logging.debug(f"[Background Job] pipeline_service.scrape_and_ingest completed for job {job_id}.")

        # EXTRACT SKILLS (jobs + subjects)
        if job_id in cancelled_jobs:
            logging.info(f"[Background Job] Job {job_id} cancelled during extract phase.")
            _emit(job_id, "extract_skills_from_jobs", "cancelled")
            _emit(job_id, "extract_subject_skills_from_supabase", "cancelled")
            await _yield_now()
            return

        _emit(job_id, "extract_skills_from_jobs", "started")
        _emit(job_id, "extract_subject_skills_from_supabase", "started")
        await _yield_now()

        logging.debug(f"[Background Job] Calling pipeline_service.extract_skills for job {job_id}...")
        await pipeline_service.extract_skills(
            extract_enabled=extract_enabled,
            use_stored_data=use_stored_data,
        )

        _emit(job_id, "extract_skills_from_jobs", "completed")
        _emit(job_id, "extract_subject_skills_from_supabase", "completed")
        await _yield_now()
        logging.debug(f"[Background Job] pipeline_service.extract_skills completed for job {job_id}.")

        # RETRAIN MODELS
        if job_id in cancelled_jobs:
            logging.info(f"[Background Job] Job {job_id} cancelled during retraining phase.")
            _emit(job_id, "retrain_ml_models", "cancelled")
            await _yield_now()
            return

        _emit(job_id, "retrain_ml_models", "started")
        await _yield_now()

        logging.debug(f"[Background Job] Calling pipeline_service.retrain_ml_models for job {job_id}...")
        await pipeline_service.retrain_ml_models(retrain=retrain_models)

        _emit(job_id, "retrain_ml_models", "completed")
        await _yield_now()
        logging.debug(f"[Background Job] pipeline_service.retrain_ml_models completed for job {job_id}.")

        # EVALUATE
        if job_id in cancelled_jobs:
            logging.info(f"[Background Job] Job {job_id} cancelled during evaluate phase.")
            _emit(job_id, "compute_subject_scores_and_save", "cancelled")
            await _yield_now()
            return

        _emit(job_id, "compute_subject_scores_and_save", "started")
        await _yield_now()

        logging.debug(f"[Background Job] Calling pipeline_service.evaluate_and_save_scores for job {job_id}...")
        report_data = await pipeline_service.evaluate_and_save_scores()

        _emit(job_id, "compute_subject_scores_and_save", "completed")
        await _yield_now()
        logging.debug(f"[Background Job] pipeline_service.evaluate_and_save_scores completed for job {job_id}.")

        # PDF GENERATION
        if job_id in cancelled_jobs:
            logging.info(f"[Background Job] Job {job_id} cancelled during PDF generation phase.")
            _emit(job_id, "generate_pdf_report", "cancelled")
            await _yield_now()
            return

        _emit(job_id, "generate_pdf_report", "started")
        await _yield_now()

        logging.debug(f"[Background Job] Calling pipeline_service.generate_and_store_pdf_report for job {job_id}...")
        pdf_path = await pipeline_service.generate_and_store_pdf_report(
            gen_pdf=generate_pdf,
            report_data=report_data,  # Pass the report data directly
        )

        # -------- Option A: ensure file exists & is non-empty before emitting "completed"
        if pdf_path:
            for _ in range(20):  # up to ~2s total
                try:
                    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.1)

        report_url: Optional[str] = None
        if pdf_path:
            filename = os.path.basename(pdf_path)
            report_url = f"/api/reports/{filename}"

        _emit(job_id, "generate_pdf_report", "completed", report_url=report_url)
        # explicit micro-yield to flush SSE frame
        await asyncio.sleep(0)

        logging.debug(f"[Background Job] pipeline_service.generate_and_store_pdf_report completed for job {job_id}.")

    except Exception as e:
        logging.error(f"[Background Job] An unhandled error occurred for job {job_id}: {e}", exc_info=True)
        _emit(job_id, "generate_pdf_report", "error")
        await _yield_now()
        # Also publish a general error event for the job
        publish(
            job_id,
            {
                "type": "error",
                "jobId": job_id,
                "timestamp": _ts(),
                "error": str(e),
                "traceback": traceback.format_exc(),
            },
        )
    finally:
        # Clean up cancelled job ID
        if job_id in cancelled_jobs:
            cancelled_jobs.remove(job_id)
        logging.info(f"[Background Job] Finished for jobId: {job_id}. Cleaned up cancelled status.")


# -------- API ROUTES --------

@router.post("/orchestrator/init")
async def init_orchestrator():
    """
    Initializes an orchestrator job and returns a jobId without starting the process.
    """
    job_id = str(uuid.uuid4())
    logging.info(f"[API] /orchestrator/init received. Initializing jobId: {job_id}")
    return {"jobId": job_id}


@router.post("/orchestrator/start-pipeline/{jobId}")
async def start_pipeline(jobId: str, payload: Dict[str, Any], background: BackgroundTasks):
    """
    Starts the orchestration pipeline for a given jobId.
    """
    logging.info(f"[API] /orchestrator/start-pipeline/{jobId} received. Starting background task.")
    if not jobId:
        logging.warning("[API] Start pipeline request missing jobId.")
        raise HTTPException(status_code=400, detail="Job ID is required.")
    background.add_task(_background_job, jobId, payload)
    return {"status": "started", "jobId": jobId}


class CancelReq(BaseModel):
    jobId: str


@router.post("/orchestrator/cancel")
async def cancel(req: CancelReq):
    """
    Mark a running orchestrator job as cancelled.
    """
    jobId = (req.jobId or "").strip()
    logging.info(f"[API] /orchestrator/cancel received for jobId: {jobId}")
    if not jobId:
        logging.warning("[API] Cancel request missing jobId.")
        raise HTTPException(status_code=400, detail="Job ID is required.")
    cancelled_jobs.add(jobId)
    logging.info(f"[API] Job {jobId} marked as cancelled.")
    return {"status": "cancelled", "jobId": jobId}


@router.get("/orchestrator/events")
async def events(request: Request, jobId: str):
    """
    Establishes an SSE connection to stream events for a specific job.
    """
    logging.info(f"[API] /orchestrator/events received for jobId: {jobId}. Establishing SSE connection.")
    if not jobId:
        logging.warning("[API] Events request missing jobId.")
        raise HTTPException(status_code=400, detail="Job ID is required.")

    queue: asyncio.Queue = subscribe(jobId)
    logging.debug(f"[API] Subscribed queue for jobId {jobId}. Queue size: {queue.qsize()}")

    async def event_stream(stream_job_id: str):
        heartbeat = 15.0  # keep-alive every 15s
        loop = asyncio.get_event_loop()
        last_sent = loop.time()
        logging.debug(f"[SSE Stream] Starting event_stream for jobId {stream_job_id}.")

        # Send padding + initial ping (helps defeat buffering/gzip proxies)
        yield ":" + (" " * 2048) + "\n\n"
        yield "event: ping\ndata: connected\n\n"

        try:
            while True:
                if await request.is_disconnected():
                    logging.info(f"[SSE Stream] Client for jobId {stream_job_id} disconnected.")
                    break

                timeout = max(0.0, heartbeat - (loop.time() - last_sent))
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout)
                    logging.debug(
                        f"[SSE Stream] Got event from queue for jobId {stream_job_id}: "
                        f"{event.get('function')} - {event.get('status')}"
                    )
                except asyncio.TimeoutError:
                    # Heartbeat comment
                    yield f": keep-alive {int(loop.time())}\n\n"
                    last_sent = loop.time()
                    logging.debug(f"[SSE Stream] Sent keep-alive for jobId {stream_job_id}.")
                    continue

                # Single-line compact JSON for SSE
                payload = json.dumps(event, separators=(",", ":"))
                yield f"data: {payload}\n\n"
                last_sent = loop.time()
                logging.debug(
                    f"[SSE Stream] Yielded data event for jobId {stream_job_id}: "
                    f"{event.get('function')} - {event.get('status')}"
                )

                # Stop the stream on final event
                if isinstance(event, dict) and (
                    (event.get("function") == "generate_pdf_report" and event.get("status") in {"completed", "error"})
                    or (event.get("type") == "error")
                ):
                    logging.info(
                        f"[SSE Stream] Stopping stream for jobId {stream_job_id} due to final event "
                        f"(type={event.get('type')}, function={event.get('function')}, status={event.get('status')})."
                    )
                    await asyncio.sleep(0.1)
                    break
        except asyncio.CancelledError:
            logging.info(f"[SSE Stream] Event stream for jobId {stream_job_id} was cancelled.")
        except Exception as e:
            logging.error(f"[SSE Stream] Unhandled exception in event_stream for jobId {stream_job_id}: {e}", exc_info=True)
        finally:
            unsubscribe(jobId, queue)  # use original jobId for unsubscribe
            logging.info(f"[SSE Stream] Unsubscribed queue for jobId {stream_job_id}.")

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        event_stream(jobId),
        media_type="text/event-stream",
        headers=headers,
    )


@router.get("/orchestrator/status")
async def status(jobId: str):
    """
    Polling fallback. Returns the latest step statuses and (if known) the last reportUrl.
    """
    logging.info(f"[API] /orchestrator/status received for jobId: {jobId}")
    if not jobId:
        logging.warning("[API] Status request missing jobId.")
        raise HTTPException(status_code=400, detail="Job ID is required.")

    steps = get_status(jobId)
    logging.debug(f"[API] Status for jobId {jobId}: {steps}")
    return JSONResponse({"steps": steps, "reportUrl": _last_report_url.get(jobId)})
