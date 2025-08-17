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

export function useOrchestrator() {
  const [steps, setSteps] = useState<ProcessStep[]>(INITIAL_STEPS);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [reportUrl, setReportUrl] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const esRef = useRef<EventSource | null>(null);
  const cancelledRef = useRef(false);

  const closeStream = () => {
    try {
      esRef.current?.close();
    } catch {}
    esRef.current = null;
  };

  // Close SSE on unmount
  useEffect(() => {
    return () => closeStream();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-download when reportUrl arrives
  useEffect(() => {
    if (!reportUrl) return;
    try {
      window.location.href = reportUrl;
    } catch {
      const a = document.createElement('a');
      a.href = reportUrl;
      a.download = `alignment_report_${Date.now()}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
  }, [reportUrl]);

  const resetUI = () => {
    setIsProcessing(true);
    setIsComplete(false);
    setReportUrl(null);
    setSteps(INITIAL_STEPS.map(s => ({ ...s, status: 'pending' })));
    cancelledRef.current = false;
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
      return data.jobId;
    }
    throw new Error('No jobId received from init endpoint');
  }

  async function startOrchestratorPipeline(id: string, source: OrchestratorSource, flags: RunFlags = {}) {
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

  /**
   * Opens the SSE connection and returns a Promise that resolves when the connection is open.
   */
  function openEventStream(id?: string | null): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!id) {
        console.error('FRONTEND: Cannot open EventSource, jobId is null.');
        return reject(new Error('Job ID is required to open EventSource.'));
      }

      // Always close any existing stream before opening a new one
      closeStream();

      const url = `${ORCHESTRATOR_EVENTS_URL}?jobId=${encodeURIComponent(id)}`;
      console.log('FRONTEND: Attempting to open EventSource to:', url);
      const es = new EventSource(url);
      esRef.current = es;

      es.onmessage = (evt) => {
        console.log('FRONTEND: Received SSE message:', evt.data);
        try {
          const payload = JSON.parse(evt.data);

          if (payload.reportUrl) {
            setReportUrl(String(payload.reportUrl));
            console.log('FRONTEND: Report URL set:', payload.reportUrl);
          }

          const fn: string | undefined = payload.function;
          const st: string | undefined = payload.status;

          if (fn && st) {
            setSteps(prev => {
              const newSteps = prev.map(s => {
                if (s.fn !== fn) return s;
                const map: Record<string, StepStatus> = {
                  started: 'in-progress',
                  completed: 'completed',
                  error: 'error',
                };
                return { ...s, status: map[st] ?? s.status };
              });
              return newSteps;
            });
          }

          if (fn === 'generate_pdf_report' && st === 'completed') {
            setIsComplete(true);
            setIsProcessing(false);
            console.log('FRONTEND: Process complete, closing SSE.');
            closeStream(); // ensure ref is cleared
          }
          if (st === 'error') {
            setIsProcessing(false);
            console.log('FRONTEND: Process error detected.');
          }
        } catch (parseError) {
          console.error('FRONTEND: Error parsing SSE message:', parseError, 'Raw data:', evt.data);
        }
      };

      es.onerror = (error) => {
        console.error('FRONTEND: SSE Error occurred:', error);
        closeStream(); // close and clear ref
        if (!isComplete && !cancelledRef.current) {
          console.log('FRONTEND: SSE Error, attempting to poll status.');
          if (id) pollStatus(id);
        }
        reject(new Error('SSE connection error.'));
      };

      es.onopen = () => {
        console.log('FRONTEND: SSE connection opened successfully for jobId:', id);
        resolve();
      };
    });
  }

  async function pollStatus(id: string) {
    if (cancelledRef.current || isComplete) return;
    try {
      const res = await fetch(`${ORCHESTRATOR_STATUS_URL}?jobId=${encodeURIComponent(id)}`);
      if (res.ok) {
        const data = await res.json() as {
          steps?: Record<string, 'pending' | 'in_progress' | 'completed' | 'error'>,
          reportUrl?: string
        };

        if (data.reportUrl) setReportUrl(data.reportUrl);

        if (data.steps) {
          setSteps(prev => {
            const newSteps = prev.map(s => {
              const st = data.steps![s.fn];
              const map: Record<string, StepStatus> = {
                pending: 'pending',
                in_progress: 'in-progress',
                completed: 'completed',
                error: 'error',
              };
              return st ? { ...s, status: map[st] } : s;
            });
            return newSteps;
          });

          const done = data.steps['generate_pdf_report'] === 'completed';
          if (done) {
            setIsComplete(true);
            setIsProcessing(false);
            console.log('FRONTEND: Polling detected process complete.');
            return;
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

      console.log('FRONTEND: Awaiting SSE connection to open...');
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

      console.log('FRONTEND: Awaiting SSE connection to open...');
      await openEventStream(currentJobId);

      await startOrchestratorPipeline(currentJobId, 'stored', {
        scrapeEnabled: true,
        extractEnabled: true,
        generatePdf: true,
        retrainModels: false,
      });
    } catch (error) {
      console.error('FRONTEND: Error in startFromStored workflow:', error);
      setIsProcessing(false);
      closeStream();
    }
  }

  async function cancel() {
    console.log('FRONTEND: Cancel requested for jobId:', jobId);
    cancelledRef.current = true;
    closeStream(); // close and clear ref immediately
    setIsProcessing(false);
    setSteps(INITIAL_STEPS.map(s => ({ ...s, status: 'pending' })));

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

  return { steps, isProcessing, isComplete, reportUrl, jobId, startFromPdf, startFromStored, cancel };
}
