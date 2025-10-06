// src/components/report/useOrchestrator.ts
'use client';

import { useEffect, useRef, useState } from 'react';
import {
  INITIAL_STEPS,
  ORCHESTRATOR_EVENTS_URL,
  ORCHESTRATOR_INIT_URL,
  ORCHESTRATOR_START_PIPELINE_URL,
  ORCHESTRATOR_STATUS_URL,
  ORCHESTRATOR_CANCEL_URL,
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

/** Always return a clean absolute URL. */
function toAbsoluteUrl(url: string): string {
  try {
    // Already absolute?
    return new URL(url).toString();
  } catch {
    const base = (API_BASE ?? '').replace(/\/+$/, '');
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

/* ---------- Typed status helpers ---------- */

const STATUS_MAP = {
  started: 'in-progress',
  completed: 'completed',
  error: 'error',
} as const;

type IncomingStatus = keyof typeof STATUS_MAP;

/** Normalize backend step status → UI StepStatus (typed). */
function mapStatus(st?: string): StepStatus {
  if (!st) return 'pending';

  // server sometimes uses "in_progress"
  if (st === 'in_progress') return 'in-progress';
  if (st === 'pending') return 'pending';

  if ((Object.keys(STATUS_MAP) as IncomingStatus[]).includes(st as IncomingStatus)) {
    return STATUS_MAP[st as IncomingStatus];
  }

  // default fallback
  return 'pending';
}

export function useOrchestrator() {
  const [steps, setSteps] = useState<ProcessStep[]>(INITIAL_STEPS);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [reportUrl, setReportUrl] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  // OPTIONAL: preview what scan-pdf parsed
  const [parsedRows, setParsedRows] = useState<any[] | null>(null);

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
        const reachable = await waitUntilReachable(reportUrl, 30, 500);
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
    setParsedRows(null);
    setSteps(INITIAL_STEPS.map((s) => ({ ...s, status: 'pending' })));
    cancelledRef.current = false;
    downloadStartedRef.current = false;
  };

  /**
   * Upload the PDF to the backend scan endpoint.
   * Backend expects field name 'pdf' => async def scan_pdf_endpoint(pdf: UploadFile = File(...))
   */
  async function uploadPdf(file: File): Promise<{ inserted: any[]; parsed_rows: any[]; raw_text_len: number }> {
    const form = new FormData();
    form.append('pdf', file);
    const url = toAbsoluteUrl(PDF_UPLOAD_URL);

    const res = await fetch(url, { method: 'POST', body: form });
    const text = await res.text().catch(() => '');
    if (!res.ok) {
      let detail = '';
      try {
        const j = JSON.parse(text);
        detail = j?.detail || '';
      } catch {}
      const explain = detail || text || `Upload failed (${res.status})`;
      throw new Error(`scan-pdf error: ${explain}`);
    }

    const data = JSON.parse(text || '{}');
    const rows = Array.isArray(data?.parsed_rows) ? data.parsed_rows : [];
    setParsedRows(rows);
    return data;
  }

  async function initOrchestratorJob() {
    const url = toAbsoluteUrl(ORCHESTRATOR_INIT_URL);
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({}),
    });
    const txt = await res.text().catch(() => '');
    if (!res.ok) throw new Error(txt || 'Failed to initialize orchestrator job');

    const data = (txt ? JSON.parse(txt) : {}) as any;
    if (data?.jobId) {
      setJobId(String(data.jobId));
      return String(data.jobId);
    }
    throw new Error('No jobId received from init endpoint');
  }

  async function startOrchestratorPipeline(
    id: string,
    source: OrchestratorSource,
    flags: RunFlags = {}
  ) {
    const url = toAbsoluteUrl(`${ORCHESTRATOR_START_PIPELINE_URL}/${encodeURIComponent(id)}`);
    const payload = {
      source,
      scrapeEnabled: flags.scrapeEnabled ?? true,
      extractEnabled: flags.extractEnabled ?? true,
      retrainModels: flags.retrainModels ?? false,
      generatePdf: flags.generatePdf ?? true,
    };

    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify(payload),
    });
    const txt = await res.text().catch(() => '');
    if (!res.ok) throw new Error(txt || `Failed to start pipeline for jobId ${id}`);
  }

  /** Opens SSE. Resolves once opened OR after a short grace period so we can fallback to polling. */
  function openEventStream(id?: string | null, graceMs = 1200): Promise<void> {
    return new Promise((resolve) => {
      if (!id) {
        resolve(); // let polling handle it
        return;
      }

      closeStream();

      const url = `${toAbsoluteUrl(ORCHESTRATOR_EVENTS_URL)}?jobId=${encodeURIComponent(id)}`;
      const es = new EventSource(url);
      esRef.current = es;

      const graceTimer = setTimeout(() => {
        if (!openedRef.current) resolve();
      }, graceMs);

      es.onopen = () => {
        openedRef.current = true;
        clearTimeout(graceTimer);
        resolve();
      };

      es.onmessage = (evt) => {
        if (!evt.data) return;
        try {
          const payload = JSON.parse(evt.data);

          if (payload?.type === 'error') {
            const failedFn: string | undefined = payload.failed_at || payload.function;
            if (failedFn) {
              setSteps((prev) =>
                prev.map((s) => (s.fn === failedFn ? { ...s, status: 'error' as StepStatus } : s))
              );
            }
            setIsProcessing(false);
            closeStream();
            if (!cancelledRef.current && id) pollStatus(id);
            return;
          }

          if (payload.reportUrl) setReportUrl(String(payload.reportUrl));

          const fn: string | undefined = payload.function;
          const st: string | undefined = payload.status;

          if (fn && st) {
            setSteps((prev) =>
              prev.map((s) => (s.fn === fn ? { ...s, status: mapStatus(st) } : s))
            );
          }

          if (fn === 'generate_pdf_report' && st === 'completed') {
            setIsComplete(true);
            setIsProcessing(false);
            closeStream();
          }
          if (st === 'error') {
            setIsProcessing(false);
          }
        } catch {
          // keep-alives or non-JSON; ignore
        }
      };

      es.onerror = () => {
        if (!cancelledRef.current && id) {
          pollStatus(id);
        }
      };
    });
  }

  async function pollStatus(id: string) {
    if (cancelledRef.current || isComplete) return;
    try {
      const url = `${toAbsoluteUrl(ORCHESTRATOR_STATUS_URL)}?jobId=${encodeURIComponent(id)}`;
      const res = await fetch(url, { cache: 'no-store' });
      if (res.ok) {
        const data = (await res.json()) as {
          steps?: Record<'pending' | 'in_progress' | 'completed' | 'error' | string, any>;
          reportUrl?: string;
        };

        if (data.reportUrl) setReportUrl(data.reportUrl);

        if (data.steps) {
          setSteps((prev) =>
            prev.map((s) => {
              const raw = data.steps![s.fn];
              return raw ? { ...s, status: mapStatus(raw) } : s;
            })
          );

          const done = data.steps['generate_pdf_report'] === 'completed';
          if (done) {
            setIsComplete(true);
            setIsProcessing(false);
            return;
          }
        }
      }
    } catch (pollError) {
      console.error('FRONTEND: Error during polling:', pollError);
    }
    setTimeout(() => pollStatus(id), 1000);
  }

  /** Fixed: upload PDF first, then run pipeline with source='stored' */
  async function startFromPdf(file: File) {
    resetUI();
    try {
      await uploadPdf(file);
      const currentJobId = await initOrchestratorJob();
      await openEventStream(currentJobId);

      await startOrchestratorPipeline(currentJobId, 'stored', {
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
    cancelledRef.current = true;
    closeStream();
    setIsProcessing(false);
    setSteps(INITIAL_STEPS.map((s) => ({ ...s, status: 'pending' })));

    if (jobId) {
      try {
        const url = toAbsoluteUrl(ORCHESTRATOR_CANCEL_URL);
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ jobId }),
        });
        if (!res.ok) {
          const txt = await res.text().catch(() => '');
          throw new Error(txt || 'Cancel request failed');
        }
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
    parsedRows, // optional preview data from scan-pdf
    startFromPdf,
    startFromStored,
    cancel,
  };
}
