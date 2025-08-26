from __future__ import annotations

import asyncio
from typing import Any, Dict, List
import logging  # used to print info/debug messages

# For each job_id, it keep a list of "subscriber queues".
# Think of it like each job has a mailbox, and multiple people can subscribe to get its letters.
_queues: Dict[str, List[asyncio.Queue]] = {}

# This just stores the latest status of each function in the job (like "started", "completed")
_status: Dict[str, Dict[str, str]] = {}


def subscribe(job_id: str) -> asyncio.Queue:
    """
    Someone wants to listen for events of a given job_id.
    We create a new queue (like a personal mailbox) and attach it to that job.
    """
    q: asyncio.Queue = asyncio.Queue()
    _queues.setdefault(job_id, []).append(q)
    _status.setdefault(job_id, {})
    logging.info(f"[EventBus] Subscribed new client for job_id: {job_id}. Total subscribers: {len(_queues[job_id])}")
    return q


def publish(job_id: str, event: Dict[str, Any]) -> None:
    """
    Send an event to EVERY subscriber queue of this job_id.
    This is like broadcasting a message to all listeners.
    """
    fn = event.get("function")
    st = event.get("status")
    if fn and st:
        # save the most recent status
        _status.setdefault(job_id, {})[fn] = st

    subscribers_count = len(_queues.get(job_id, []))
    logging.debug(f"[EventBus] Publishing event for job {job_id} (Fn: {fn}, Status: {st}). Attempting to push to {subscribers_count} queues.")

    # go through all subscriber mailboxes and drop in the event
    for q in _queues.get(job_id, []):
        try:
            q.put_nowait(event)  # don't wait, just push event instantly
            logging.debug(f"[EventBus] Successfully put event to queue for job {job_id}.")
        except asyncio.QueueFull:
            # if a queue is overloaded, just drop the message
            logging.warning(f"[EventBus] Queue for job {job_id} is full. Event dropped for one subscriber.")
            pass
        except Exception as e:
            logging.error(f"[EventBus] Error putting event to queue for job {job_id}: {e}", exc_info=True)


def get_status(job_id: str) -> Dict[str, str]:
    """
    Return the latest known status of functions for this job.
    Example: {"scrape": "completed", "extract": "started"}
    """
    logging.debug(f"[EventBus] Fetching status for job_id: {job_id}.")
    return _status.get(job_id, {})


def unsubscribe(job_id: str, queue: asyncio.Queue | None = None) -> None:
    """
    Stop listening to events.
    - If queue is provided → remove just that subscriber.
    - If no queue is provided → remove all subscribers of that job.
    """
    logging.info(f"[EventBus] Unsubscribe request for job_id: {job_id}.")
    if queue is not None:
        subs = _queues.get(job_id)
        if subs and queue in subs:
            subs.remove(queue)
            logging.info(f"[EventBus] Removed one subscriber for job_id: {job_id}. Remaining: {len(subs)}")
            if not subs:
                # if no more subscribers, remove the job entry
                _queues.pop(job_id, None)
                logging.info(f"[EventBus] No more subscribers for job_id: {job_id}. Removing job entry.")
        else:
            logging.warning(f"[EventBus] Attempted to unsubscribe queue for job_id {job_id} but queue not found.")
    else:
        # remove everyone at once
        _queues.pop(job_id, None)
        logging.info(f"[EventBus] Unsubscribed all clients for job_id: {job_id}.")


def clear(job_id: str) -> None:
    """
    Totally wipe out everything for this job_id:
    - remove all queues (subscribers)
    - remove all stored status
    """
    logging.info(f"[EventBus] Clearing all data for job_id: {job_id}.")
    _queues.pop(job_id, None)
    _status.pop(job_id, None)
