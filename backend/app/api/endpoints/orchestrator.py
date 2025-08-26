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

# importing some helper functions for pub/sub (like event notifications)
from ...core.event_bus import publish, subscribe, unsubscribe, get_status
# this connects to the actual services that run scraping, extraction, etc.
from ...services import orchestrator as pipeline_service

router = APIRouter()

# saves the last generated PDF report url per job
_last_report_url: Dict[str, str] = {}
# keeps track of jobs that were cancelled
cancelled_jobs: set[str] = set()


# helper to get current UTC time in ISO format
def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# this sets environment variables based on payload (used like feature toggles)
def _apply_optional_env_flags(payload: Dict[str, Any]) -> None:
    if "scrapeEnabled" in payload:
        os.environ["SCRAPE_ENABLED"] = "true" if payload["scrapeEnabled"] else "false"
    if "extractEnabled" in payload:
        os.environ["EXTRACT_ENABLED"] = "true" if payload["extractEnabled"] else "false"
    if "retrainModels" in payload:
        os.environ["RETRAIN_MODELS"] = "true" if payload["retrainModels"] else "false"
    if "generatePdf" in payload:
        os.environ["GENERATE_PDF"] = "true" if payload["generatePdf"] else "false"


# this sends out events about job progress (like "started", "completed")
def _emit(job_id: str, fn: str, status: str, report_url: Optional[str] = None) -> None:
    event: Dict[str, Any] = {"function": fn, "status": status, "timestamp": _ts()}
    if report_url:
        event["reportUrl"] = report_url
        _last_report_url[job_id] = report_url
    logging.info(f"[_emit] Publishing: Job={job_id}, Function={fn}, Status={status}, ReportUrl={report_url or 'N/A'}")
    publish(job_id, event)


# just a small pause to let async events flush out
async def _yield_now() -> None:
    await asyncio.sleep(0)


# the BIG background function that runs the whole pipeline
async def _background_job(job_id: str, payload: Dict[str, Any]) -> None:
    """
    This runs all steps one by one:
    scrape jobs → extract skills → retrain models → evaluate → generate PDF
    """
    logging.info(f"[Background Job] Started for jobId: {job_id} with payload: {payload}")
    source = str(payload.get("source", "fresh")).lower()
    use_stored_data = (source == "stored")
    retrain_models_flag = payload.get("retrainModels", False)
    generate_pdf_flag = payload.get("generatePdf", True)

    # apply flags from payload
    _apply_optional_env_flags(payload)

    # final values after mixing env + payload
    scrape_enabled = os.getenv("SCRAPE_ENABLED", "true").lower() == "true"
    extract_enabled = os.getenv("EXTRACT_ENABLED", "true").lower() == "true"
    retrain_models = os.getenv("RETRAIN_MODELS", "false").lower() == "true" or retrain_models_flag
    generate_pdf = os.getenv("GENERATE_PDF", "true").lower() == "true" or generate_pdf_flag

    logging.debug(f"[Background Job] Effective flags: Scrape={scrape_enabled}, Extract={extract_enabled}, Retrain={retrain_models}, PDF={generate_pdf}")

    try:
        # --- STEP 1: SCRAPE ---
        if job_id in cancelled_jobs:
            _emit(job_id, "scrape_jobs_from_google_jobs", "cancelled")
            return
        _emit(job_id, "scrape_jobs_from_google_jobs", "started")
        await _yield_now()
        await pipeline_service.scrape_and_ingest(scrape_enabled=scrape_enabled)
        _emit(job_id, "scrape_jobs_from_google_jobs", "completed")
        await _yield_now()

        # --- STEP 2: EXTRACT SKILLS ---
        if job_id in cancelled_jobs:
            _emit(job_id, "extract_skills_from_jobs", "cancelled")
            _emit(job_id, "extract_subject_skills_from_supabase", "cancelled")
            return
        _emit(job_id, "extract_skills_from_jobs", "started")
        _emit(job_id, "extract_subject_skills_from_supabase", "started")
        await _yield_now()
        await pipeline_service.extract_skills(extract_enabled=extract_enabled, use_stored_data=use_stored_data)
        _emit(job_id, "extract_skills_from_jobs", "completed")
        _emit(job_id, "extract_subject_skills_from_supabase", "completed")
        await _yield_now()

        # --- STEP 3: RETRAIN MODELS ---
        if job_id in cancelled_jobs:
            _emit(job_id, "retrain_ml_models", "cancelled")
            return
        _emit(job_id, "retrain_ml_models", "started")
        await _yield_now()
        await pipeline_service.retrain_ml_models(retrain=retrain_models)
        _emit(job_id, "retrain_ml_models", "completed")
        await _yield_now()

        # --- STEP 4: EVALUATE COURSES ---
        if job_id in cancelled_jobs:
            _emit(job_id, "compute_subject_scores_and_save", "cancelled")
            return
        _emit(job_id, "compute_subject_scores_and_save", "started")
        await _yield_now()
        report_data = await pipeline_service.evaluate_and_save_scores()
        _emit(job_id, "compute_subject_scores_and_save", "completed")
        await _yield_now()

        # --- STEP 5: GENERATE PDF ---
        if job_id in cancelled_jobs:
            _emit(job_id, "generate_pdf_report", "cancelled")
            return
        _emit(job_id, "generate_pdf_report", "started")
        await _yield_now()

        pdf_info = await pipeline_service.generate_and_store_pdf_report(gen_pdf=generate_pdf, report_data=report_data)

        report_url: Optional[str] = None
        if pdf_info and isinstance(pdf_info, dict):
            report_url = pdf_info.get("url")
            pdf_path = pdf_info.get("path")
            # wait a bit until file actually exists (avoid race condition)
            if pdf_path:
                for _ in range(20):  # max ~2 seconds
                    try:
                        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.1)

        _emit(job_id, "generate_pdf_report", "completed", report_url=report_url)
        await asyncio.sleep(0)

    except Exception as e:
        # if something fails, log it and notify frontend
        logging.error(f"[Background Job] Error for job {job_id}: {e}", exc_info=True)
        _emit(job_id, "generate_pdf_report", "error")
        publish(job_id, {
            "type": "error",
            "jobId": job_id,
            "timestamp": _ts(),
            "error": str(e),
            "traceback": traceback.format_exc(),
        })
    finally:
        # clean up cancelled job if it was marked
        if job_id in cancelled_jobs:
            cancelled_jobs.remove(job_id)
        logging.info(f"[Background Job] Finished for jobId: {job_id}")


# -------- API ROUTES --------

# create a new job id
@router.post("/orchestrator/init")
async def init_orchestrator():
    job_id = str(uuid.uuid4())
    return {"jobId": job_id}


# start pipeline in background
@router.post("/orchestrator/start-pipeline/{jobId}")
async def start_pipeline(jobId: str, payload: Dict[str, Any], background: BackgroundTasks):
    if not jobId:
        raise HTTPException(status_code=400, detail="Job ID is required.")
    background.add_task(_background_job, jobId, payload)
    return {"status": "started", "jobId": jobId}


# request body model for cancelling jobs
class CancelReq(BaseModel):
    jobId: str


# cancel a running job
@router.post("/orchestrator/cancel")
async def cancel(req: CancelReq):
    jobId = (req.jobId or "").strip()
    if not jobId:
        raise HTTPException(status_code=400, detail="Job ID is required.")
    cancelled_jobs.add(jobId)
    return {"status": "cancelled", "jobId": jobId}


# stream events to frontend (SSE - Server Sent Events)
@router.get("/orchestrator/events")
async def events(request: Request, jobId: str):
    if not jobId:
        raise HTTPException(status_code=400, detail="Job ID is required.")
    queue: asyncio.Queue = subscribe(jobId)

    async def event_stream(stream_job_id: str):
        heartbeat = 15.0
        loop = asyncio.get_event_loop()
        last_sent = loop.time()
        # SSE requires at least one comment line to keep connection open
        yield ":" + (" " * 2048) + "\n\n"
        yield "event: ping\ndata: connected\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                timeout = max(0.0, heartbeat - (loop.time() - last_sent))
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    # send keep-alive ping
                    yield f": keep-alive {int(loop.time())}\n\n"
                    last_sent = loop.time()
                    continue
                payload = json.dumps(event, separators=(",", ":"))
                yield f"data: {payload}\n\n"
                last_sent = loop.time()
                # stop stream if PDF finished or error occurred
                if isinstance(event, dict) and (
                    (event.get("function") == "generate_pdf_report" and event.get("status") in {"completed", "error"})
                    or (event.get("type") == "error")
                ):
                    await asyncio.sleep(0.1)
                    break
        finally:
            unsubscribe(jobId, queue)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream(jobId), media_type="text/event-stream", headers=headers)


# return current status of job (steps + last report url)
@router.get("/orchestrator/status")
async def status(jobId: str):
    if not jobId:
        raise HTTPException(status_code=400, detail="Job ID is required.")
    steps = get_status(jobId)
    return JSONResponse({"steps": steps, "reportUrl": _last_report_url.get(jobId)})
