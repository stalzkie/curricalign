# app/core/event_bus.py
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple
import logging # Added logging import here

# Configure logging for the event_bus module
# If your main.py already sets up global logging, this can be simplified or removed
# logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s [event_bus] %(message)s")

# For each job_id, keep a list of subscriber queues
_queues: Dict[str, List[asyncio.Queue]] = {}
# Simple latest status per function
_status: Dict[str, Dict[str, str]] = {}

def subscribe(job_id: str) -> asyncio.Queue:
    """
    Register a new subscriber for this job_id and return a dedicated asyncio.Queue.
    Multiple subscribers are supported and each gets every event (broadcast).
    """
    q: asyncio.Queue = asyncio.Queue()
    _queues.setdefault(job_id, []).append(q)
    _status.setdefault(job_id, {})
    logging.info(f"[EventBus] Subscribed new client for job_id: {job_id}. Total subscribers: {len(_queues[job_id])}")
    return q

def publish(job_id: str, event: Dict[str, Any]) -> None:
    """
    Broadcast an event to all subscribers for job_id.
    Synchronous (uses put_nowait); safe to call from background threads.
    """
    fn = event.get("function")
    st = event.get("status")
    if fn and st:
        _status.setdefault(job_id, {})[fn] = st

    subscribers_count = len(_queues.get(job_id, []))
    logging.debug(f"[EventBus] Publishing event for job {job_id} (Fn: {fn}, Status: {st}). Attempting to push to {subscribers_count} queues.")

    for q in _queues.get(job_id, []):
        try:
            q.put_nowait(event)
            logging.debug(f"[EventBus] Successfully put event to queue for job {job_id}.")
        except asyncio.QueueFull:
            logging.warning(f"[EventBus] Queue for job {job_id} is full. Event dropped for one subscriber.")
            pass # Handle backpressure by dropping the event
        except Exception as e:
            logging.error(f"[EventBus] Error putting event to queue for job {job_id}: {e}", exc_info=True)


def get_status(job_id: str) -> Dict[str, str]:
    """Return the latest function->status mapping for this job."""
    logging.debug(f"[EventBus] Fetching status for job_id: {job_id}.")
    return _status.get(job_id, {})

def unsubscribe(job_id: str, queue: asyncio.Queue | None = None) -> None:
    """
    Remove a specific subscriber queue (if provided) or all subscribers for job_id.
    Does not clear status; use clear(job_id) to fully reset.
    """
    logging.info(f"[EventBus] Unsubscribe request for job_id: {job_id}.")
    if queue is not None:
        subs = _queues.get(job_id)
        if subs and queue in subs:
            subs.remove(queue)
            logging.info(f"[EventBus] Removed one subscriber for job_id: {job_id}. Remaining: {len(subs)}")
            if not subs:
                _queues.pop(job_id, None)
                logging.info(f"[EventBus] No more subscribers for job_id: {job_id}. Removing job entry.")
        else:
            logging.warning(f"[EventBus] Attempted to unsubscribe queue for job_id {job_id} but queue not found.")
    else:
        _queues.pop(job_id, None)
        logging.info(f"[EventBus] Unsubscribed all clients for job_id: {job_id}.")

def clear(job_id: str) -> None:
    """Remove all queues and status for a job_id."""
    logging.info(f"[EventBus] Clearing all data for job_id: {job_id}.")
    _queues.pop(job_id, None)
    _status.pop(job_id, None)

