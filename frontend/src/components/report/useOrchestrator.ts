// useOrchestrator.ts
'use client';

import { useEffect, useRef, useState } from 'react';
import {
  INITIAL_STEPS,
  ORCHESTRATOR_EVENTS_URL,
  ORCHESTRATOR_INIT_URL,
  ORCHESTRATOR_START_PIPELINE_URL,
  ORCHESTRATOR_STATUS_URL,
  PDF_UPLOAD_URL,
  API_BASE,
} from './constants';
import type { OrchestratorSource, ProcessStep, StepStatus } from './types';

type RunFlags = {
  scrapeEnabled?: boolean;
  extractEnabled?: boolean;
  retrainModels?: boolean;
  generatePdf?: boolean;
};

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

function toAbsoluteUrl(url: string): string {
  try {
    return new URL(url).toString();
  } catch {
    const base = API_BASE?.replace(/\/+$/, '') ?? '';
    const path = url.startsWith('/') ? url : `/${url}`;
    return `${base}${path}`;
  }
}

/** Probe URL until it responds OK. Tries HEAD, falls back to GET if needed. */
async function waitUntilReachable(url: string, tries = 10, delayMs = 500): Promise<boolean> {
  const abs = toAbsoluteUrl(url);
  for (let i = 0; i < tries; i++) {
    const bust = `_t=${Date.now()}-${i}`;
    const sep = abs.includes('?') ? '&' : '?';
    const probeUrl = `${abs}${sep}${bust}`;
    try {
      let res = await fetch(probeUrl, { method: 'HEAD', cache: 'no-store' });
      if (res.ok) return true;

      if (res.status === 405 || res.status === 501) {
        res = await fetch(probeUrl, { method: 'GET', cache: 'no-store' });
        if (res.ok) return true;
      }
    } catch {
      // ignore and retry
    }
    await sleep(delayMs);
  }
  return false;
}

/** Download a URL as a file without page navigation. */
async function downloadUrlAsFile(url: string, filename: string) {
  const abs = toAbsoluteUrl(url);
  const bust = abs.includes('?') ? '&' : '?';
  const res = await fetch(`${abs}${bust}_dl=${Date.now()}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

export function useOrchestrator() {
  const [steps, setSteps] = useState<ProcessStep[]>(INITIAL_STEPS);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [reportUrl, setReportUrl] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const esRef = useRef<EventSource | null>(null);
  const cancelledRef = useRef(false);
  const openedRef = useRef(false);
  const downloadStartedRef = useRef(false);

  const closeStream = () => {
    try {
      esRef.current?.close();
    } catch {}
    esRef.current = null;
    openedRef.current = false;
  };

  useEffect(() => {
    return () => closeStream();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-download when reportUrl arrives — WITHOUT navigating
  useEffect(() => {
    (async () => {
      if (!reportUrl || downloadStartedRef.current) return;
      downloadStartedRef.current = true;
      try {
        const reachable = await waitUntilReachable(reportUrl, 14, 500);
        if (!reachable) throw new Error('Report URL is not reachable yet');
        const suggested = `alignment_report_${jobId ?? Date.now()}.pdf`;
        await downloadUrlAsFile(reportUrl, suggested);
      } catch (err) {
        console.error('FRONTEND: Auto-download failed:', err);
        downloadStartedRef.current = false;
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportUrl, jobId]);

  const resetUI = () => {
    setIsProcessing(true);
    setIsComplete(false);
    setReportUrl(null);
    setSteps(INITIAL_STEPS.map((s) => ({ ...s, status: 'pending' })));
    cancelledRef.current = false;
    downloadStartedRef.current = false;
  };

  async function uploadPdf(file: File) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(PDF_UPLOAD_URL, { method: 'POST', body: form });
    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      throw new Error(txt || 'Failed to upload PDF');
    }
  }

  async function initOrchestratorJob() {
    console.log('FRONTEND: Requesting new jobId from backend...');
    const res = await fetch(ORCHESTRATOR_INIT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      throw new Error(txt || 'Failed to initialize orchestrator job');
    }
    const data = await res.json().catch(() => ({}));
    if (data?.jobId) {
      setJobId(String(data.jobId));
      console.log('FRONTEND: Received jobId:', data.jobId);
      return data.jobId as string;
    }
    throw new Error('No jobId received from init endpoint');
  }

  async function startOrchestratorPipeline(
    id: string,
    source: OrchestratorSource,
    flags: RunFlags = {}
  ) {
    console.log('FRONTEND: Requesting backend to START pipeline for jobId:', id);
    const payload = {
      source,
      scrapeEnabled: flags.scrapeEnabled ?? true,
      extractEnabled: flags.extractEnabled ?? true,
      retrainModels: flags.retrainModels ?? false,
      generatePdf: flags.generatePdf ?? true,
    };

    const res = await fetch(`${ORCHESTRATOR_START_PIPELINE_URL}/${encodeURIComponent(id)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      throw new Error(txt || `Failed to start pipeline for jobId ${id}`);
    }
    console.log('FRONTEND: Backend acknowledged pipeline start for jobId:', id);
  }

  /** Opens SSE. Resolves once opened OR after a short grace period so we can fallback to polling. */
  function openEventStream(id?: string | null, graceMs = 1200): Promise<void> {
    return new Promise((resolve) => {
      if (!id) {
        console.error('FRONTEND: Cannot open EventSource, jobId is null.');
        resolve(); // let polling handle it
        return;
      }

      closeStream();

      const url = `${ORCHESTRATOR_EVENTS_URL}?jobId=${encodeURIComponent(id)}`;
      console.log('FRONTEND: Attempting to open EventSource to:', url);
      const es = new EventSource(url);
      esRef.current = es;

      const graceTimer = setTimeout(() => {
        if (!openedRef.current) {
          console.warn('FRONTEND: SSE did not open within grace period; continuing with polling fallback.');
          resolve();
        }
      }, graceMs);

      es.onopen = () => {
        openedRef.current = true;
        console.log('FRONTEND: SSE connection opened successfully for jobId:', id);
        clearTimeout(graceTimer);
        resolve();
      };

      es.onmessage = (evt) => {
        if (!evt.data) return;
        try {
          const payload = JSON.parse(evt.data);

          // --- Handle explicit pipeline error events ---
          if (payload?.type === 'error') {
            console.error('PIPELINE ERROR:', payload.failed_at || payload.function, payload.error);
            // Mark the failed step as error if provided
            const failedFn: string | undefined = payload.failed_at || payload.function;
            if (failedFn) {
              setSteps((prev) =>
                prev.map((s) => (s.fn === failedFn ? { ...s, status: 'error' } : s))
              );
            }
            setIsProcessing(false);
            closeStream();
            if (!cancelledRef.current && id) pollStatus(id);
            return; // stop handling this message
          }

          if (payload.reportUrl) {
            setReportUrl(String(payload.reportUrl));
            console.log('FRONTEND: Report URL set:', payload.reportUrl);
          }

          const fn: string | undefined = payload.function;
          const st: string | undefined = payload.status;

          if (fn && st) {
            setSteps((prev) =>
              prev.map((s) => {
                if (s.fn !== fn) return s;
                const map: Record<string, StepStatus> = {
                  started: 'in-progress',
                  completed: 'completed',
                  error: 'error',
                };
                return { ...s, status: map[st] ?? s.status };
              })
            );

            if (fn === 'final_checking' && st === 'completed') {
              console.log('FRONTEND: Final Validation step completed.');
            }
          }

          if (fn === 'generate_pdf_report' && st === 'completed') {
            setIsComplete(true);
            setIsProcessing(false);
            console.log('FRONTEND: Process complete, closing SSE.');
            closeStream();
          }
          if (st === 'error') {
            setIsProcessing(false);
            console.log('FRONTEND: Process error detected.');
          }
        } catch {
          // keep-alives or non-JSON; ignore
        }
      };

      es.onerror = (error) => {
        console.error('FRONTEND: SSE Error occurred:', error);
        if (!cancelledRef.current && id) {
          pollStatus(id);
        }
      };
    });
  }

  async function pollStatus(id: string) {
    if (cancelledRef.current || isComplete) return;
    try {
      const res = await fetch(`${ORCHESTRATOR_STATUS_URL}?jobId=${encodeURIComponent(id)}`, {
        cache: 'no-store',
      });
      if (res.ok) {
        const data = (await res.json()) as {
          steps?: Record<'pending' | 'in_progress' | 'completed' | 'error' | string, any>;
          reportUrl?: string;
        };

        if (data.reportUrl) setReportUrl(data.reportUrl);

        if (data.steps) {
          setSteps((prev) =>
            prev.map((s) => {
              const st = data.steps![s.fn];
              const map: Record<string, StepStatus> = {
                pending: 'pending',
                in_progress: 'in-progress',
                completed: 'completed',
                error: 'error',
              };
              return st ? { ...s, status: map[st] ?? s.status } : s;
            })
          );

          const done = data.steps['generate_pdf_report'] === 'completed';
          if (done) {
            setIsComplete(true);
            setIsProcessing(false);
            console.log('FRONTEND: Polling detected process complete.');
            return;
          }

          if (data.steps['final_checking'] === 'completed') {
            console.log('FRONTEND: Final Validation step completed (via polling).');
          }
        }
      }
    } catch (pollError) {
      console.error('FRONTEND: Error during polling:', pollError);
    }
    setTimeout(() => pollStatus(id), 1000);
  }

  async function startFromPdf(file: File) {
    resetUI();
    try {
      const currentJobId = await initOrchestratorJob();

      console.log('FRONTEND: Opening SSE (with polling fallback)...');
      await openEventStream(currentJobId);

      console.log('FRONTEND: Starting PDF upload...');
      await uploadPdf(file);
      console.log('FRONTEND: PDF upload complete.');

      await startOrchestratorPipeline(currentJobId, 'pdf', {
        scrapeEnabled: true,
        extractEnabled: true,
        generatePdf: true,
        retrainModels: false,
      });

      pollStatus(currentJobId);
    } catch (error) {
      console.error('FRONTEND: Error in startFromPdf workflow:', error);
      setIsProcessing(false);
      closeStream();
    }
  }

  async function startFromStored() {
    resetUI();
    try {
      const currentJobId = await initOrchestratorJob();

      console.log('FRONTEND: Opening SSE (with polling fallback)...');
      await openEventStream(currentJobId);

      await startOrchestratorPipeline(currentJobId, 'stored', {
        scrapeEnabled: true,
        extractEnabled: true,
        generatePdf: true,
        retrainModels: false,
      });

      pollStatus(currentJobId);
    } catch (error) {
      console.error('FRONTEND: Error in startFromStored workflow:', error);
      setIsProcessing(false);
      closeStream();
    }
  }

  async function cancel() {
    console.log('FRONTEND: Cancel requested for jobId:', jobId);
    cancelledRef.current = true;
    closeStream();
    setIsProcessing(false);
    setSteps(INITIAL_STEPS.map((s) => ({ ...s, status: 'pending' })));

    if (jobId) {
      try {
        const url = `${API_BASE}/api/orchestrator/cancel`;
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ jobId }),
        });
        if (!res.ok) {
          const txt = await res.text().catch(() => '');
          throw new Error(txt || 'Cancel request failed');
        }
        console.log('FRONTEND: Cancel request sent to backend.');
      } catch (cancelError) {
        console.error('FRONTEND: Error sending cancel request:', cancelError);
      }
    }
  }

  return {
    steps,
    isProcessing,
    isComplete,
    reportUrl,
    jobId,
    startFromPdf,
    startFromStored,
    cancel,
  };
}
