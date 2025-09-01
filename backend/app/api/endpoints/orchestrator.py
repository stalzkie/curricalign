from __future__ import annotations

import os
import json
import traceback
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
# import logging

from fastapi import APIRouter, BackgroundTasks, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

# pub/sub helpers
from ...core.event_bus import publish, subscribe, unsubscribe, get_status
# pipeline service (scraping, extraction, evaluation, pdf)
from ...services import orchestrator as pipeline_service
# NEW: import the final check
from ...services.final_checking import run_final_checks

router = APIRouter()

_last_report_url: Dict[str, str] = {}
cancelled_jobs: set[str] = set()


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(job_id: str, fn: str, status: str, report_url: Optional[str] = None) -> None:
    event: Dict[str, Any] = {"function": fn, "status": status, "timestamp": _ts()}
    if report_url:
        event["reportUrl"] = report_url
        _last_report_url[job_id] = report_url
    logging.info(
        f"[_emit] Publishing: Job={job_id}, Function={fn}, Status={status}, ReportUrl={report_url or 'N/A'}"
    )
    publish(job_id, event)


async def _yield_now() -> None:
    await asyncio.sleep(0)


def _bool_from(payload: Dict[str, Any], payload_key: str, env_key: str, default: bool) -> bool:
    """Resolve a boolean flag with per-request override and env fallback (no env mutation)."""
    if payload_key in payload:
        return bool(payload[payload_key])
    raw = os.getenv(env_key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


async def _background_job(job_id: str, payload: Dict[str, Any]) -> None:
    """
    Runs pipeline steps sequentially:
    scrape → extract → retrain → evaluate → final check → PDF
    """
    logging.info(f"[Background Job] Started for jobId: {job_id} with payload: {payload}")
    source = str(payload.get("source", "fresh")).lower()
    use_stored_data = (source == "stored")

    # Per-job flags (no global env mutation)
    scrape_enabled = _bool_from(payload, "scrapeEnabled", "SCRAPE_ENABLED", True)
    extract_enabled = _bool_from(payload, "extractEnabled", "EXTRACT_ENABLED", True)
    retrain_models = _bool_from(payload, "retrainModels", "RETRAIN_MODELS", False)
    generate_pdf = _bool_from(payload, "generatePdf", "GENERATE_PDF", True)

    logging.debug(
        f"[Background Job] Effective flags: "
        f"Scrape={scrape_enabled}, Extract={extract_enabled}, Retrain={retrain_models}, PDF={generate_pdf}, "
        f"UseStoredData={use_stored_data}"
    )

    try:
        # STEP 1: SCRAPE
        if job_id in cancelled_jobs:
            _emit(job_id, "scrape_jobs_from_google_jobs", "cancelled")
            return
        _emit(job_id, "scrape_jobs_from_google_jobs", "started")
        await _yield_now()
        await pipeline_service.scrape_and_ingest(scrape_enabled=scrape_enabled)
        _emit(job_id, "scrape_jobs_from_google_jobs", "completed")
        await _yield_now()

        # STEP 2: EXTRACT SKILLS
        if job_id in cancelled_jobs:
            _emit(job_id, "extract_skills_from_jobs", "cancelled")
            _emit(job_id, "extract_subject_skills_from_supabase", "cancelled")
            return
        _emit(job_id, "extract_skills_from_jobs", "started")
        _emit(job_id, "extract_subject_skills_from_supabase", "started")
        await _yield_now()
        await pipeline_service.extract_skills(
            extract_enabled=extract_enabled, use_stored_data=use_stored_data
        )
        _emit(job_id, "extract_skills_from_jobs", "completed")
        _emit(job_id, "extract_subject_skills_from_supabase", "completed")
        await _yield_now()

        # STEP 3: RETRAIN MODELS
        if job_id in cancelled_jobs:
            _emit(job_id, "retrain_ml_models", "cancelled")
            return
        _emit(job_id, "retrain_ml_models", "started")
        await _yield_now()
        await pipeline_service.retrain_ml_models(retrain=retrain_models)
        _emit(job_id, "retrain_ml_models", "completed")
        await _yield_now()

        # STEP 4: EVALUATE COURSES
        if job_id in cancelled_jobs:
            _emit(job_id, "compute_subject_scores_and_save", "cancelled")
            return
        _emit(job_id, "compute_subject_scores_and_save", "started")
        await _yield_now()
        raw_report_data = await pipeline_service.evaluate_and_save_scores()
        _emit(job_id, "compute_subject_scores_and_save", "completed")
        await _yield_now()

        # STEP 4.5: FINAL CHECK (NEW)
        if job_id in cancelled_jobs:
            _emit(job_id, "final_checking", "cancelled")
            return
        _emit(job_id, "final_checking", "started")
        await _yield_now()
        validated_data = await run_final_checks(raw_report_data, strict=True)
        _emit(job_id, "final_checking", "completed")
        await _yield_now()

        # STEP 5: GENERATE PDF
        if job_id in cancelled_jobs:
            _emit(job_id, "generate_pdf_report", "cancelled")
            return
        _emit(job_id, "generate_pdf_report", "started")
        await _yield_now()

        pdf_info = await pipeline_service.generate_and_store_pdf_report(
            gen_pdf=generate_pdf, report_data=validated_data
        )

        report_url: Optional[str] = None
        if pdf_info and isinstance(pdf_info, dict):
            report_url = pdf_info.get("url")
            pdf_path = pdf_info.get("path")
            if pdf_path:
                for _ in range(20):  # wait ~2s max
                    try:
                        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.1)

        _emit(job_id, "generate_pdf_report", "completed", report_url=report_url)
        await asyncio.sleep(0)

    except Exception as e:
        logging.error(f"[Background Job] Error for job {job_id}: {e}", exc_info=True)
        _emit(job_id, "generate_pdf_report", "error")
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
        if job_id in cancelled_jobs:
            cancelled_jobs.remove(job_id)
        logging.info(f"[Background Job] Finished for jobId: {job_id}")


# ---------------- API ROUTES ----------------

@router.post("/orchestrator/init")
async def init_orchestrator():
    job_id = str(uuid.uuid4())
    return {"jobId": job_id}


@router.post("/orchestrator/start-pipeline/{jobId}")
async def start_pipeline(jobId: str, payload: Dict[str, Any], background: BackgroundTasks):
    if not jobId:
        raise HTTPException(status_code=400, detail="Job ID is required.")
    background.add_task(_background_job, jobId, payload)
    return {"status": "started", "jobId": jobId}


class CancelReq(BaseModel):
    jobId: str


@router.post("/orchestrator/cancel")
async def cancel(req: CancelReq):
    jobId = (req.jobId or "").strip()
    if not jobId:
        raise HTTPException(status_code=400, detail="Job ID is required.")
    cancelled_jobs.add(jobId)
    return {"status": "cancelled", "jobId": jobId}


@router.get("/orchestrator/events")
async def events(request: Request, jobId: str):
    if not jobId:
        raise HTTPException(status_code=400, detail="Job ID is required.")
    queue: asyncio.Queue = subscribe(jobId)

    async def event_stream(stream_job_id: str):
        heartbeat = 15.0
        loop = asyncio.get_event_loop()
        # initial padding to defeat some proxies
        yield ":" + (" " * 2048) + "\n\n"
        # initial ping
        yield "event: ping\ndata: connected\n\n"
        last_sent = loop.time()  # ensure heartbeat timer starts after initial ping

        try:
            while True:
                if await request.is_disconnected():
                    break

                timeout = max(0.0, heartbeat - (loop.time() - last_sent))
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    # heartbeat comment line
                    yield f": keep-alive {int(loop.time())}\n\n"
                    last_sent = loop.time()
                    continue

                payload = json.dumps(event, separators=(",", ":"))
                yield f"data: {payload}\n\n"
                last_sent = loop.time()

                # ---- TERMINATION LOGIC (Option B) ----
                # Close stream on:
                # 1) Any explicit error (type: error)
                # 2) PDF step completed/error/cancelled
                # 3) Any step with status: cancelled
                if isinstance(event, dict):
                    etype = event.get("type")
                    fn = event.get("function")
                    st = event.get("status")

                    if etype == "error":
                        await asyncio.sleep(0.1)
                        break

                    if fn == "generate_pdf_report" and st in {"completed", "error", "cancelled"}:
                        await asyncio.sleep(0.1)
                        break

                    if st == "cancelled":
                        await asyncio.sleep(0.1)
                        break
                # --------------------------------------

        finally:
            unsubscribe(jobId, queue)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream(jobId), media_type="text/event-stream", headers=headers)


@router.get("/orchestrator/status")
async def status(jobId: str):
    if not jobId:
        raise HTTPException(status_code=400, detail="Job ID is required.")
    steps = get_status(jobId)
    return JSONResponse({"steps": steps, "reportUrl": _last_report_url.get(jobId)})
