'use client';
import { useState, useRef } from 'react';
import { RiFilePdfLine, RiPlayListAddLine } from 'react-icons/ri';

type StepEvent = {
  function?: string;
  status?: string;
  timestamp?: string;
  reportUrl?: string;
  type?: string;
  error?: string;
};

const API_BASE =
  process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, '') || 'http://localhost:8000';

export default function UploadCard() {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<StepEvent[]>([]);
  const [parsedRows, setParsedRows] = useState<any[]>([]);
  const esRef = useRef<EventSource | null>(null);

  const closeStream = () => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  };

  // full flow: scan PDF -> store courses -> start pipeline
  const handleGenerateFromPdf = async () => {
    if (!file) return;
    setBusy(true);
    setEvents([]);
    setParsedRows([]);
    closeStream();

    try {
      // 1) send PDF to scan endpoint
      const fd = new FormData();
      fd.append('pdf', file);
      const scanRes = await fetch(`${API_BASE}/api/scan-pdf`, {
        method: 'POST',
        body: fd,
      });
      if (!scanRes.ok) throw new Error('scan-pdf failed');
      const scanData = await scanRes.json();
      setParsedRows(scanData.parsed_rows || []);

      // 2) init orchestrator
      const initRes = await fetch(`${API_BASE}/api/orchestrator/init`, { method: 'POST' });
      const { jobId } = await initRes.json();

      // 3) start pipeline
      const payload = {
        source: 'pdf',
        scrapeEnabled: true,
        extractEnabled: true,
        retrainModels: false,
        generatePdf: true,
      };
      await fetch(`${API_BASE}/api/orchestrator/start-pipeline/${jobId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      // 4) subscribe to events
      const es = new EventSource(`${API_BASE}/api/orchestrator/events?jobId=${jobId}`);
      esRef.current = es;
      es.onmessage = (ev) => {
        try {
          const data: StepEvent = JSON.parse(ev.data);
          setEvents((prev) => [...prev, data]);
        } catch {}
      };
      es.onerror = () => closeStream();
    } catch (err) {
      console.error(err);
      alert('Pipeline failed');
    } finally {
      setBusy(false);
    }
  };

  const handleUseStored = async () => {
    setBusy(true);
    setEvents([]);
    closeStream();

    try {
      const initRes = await fetch(`${API_BASE}/api/orchestrator/init`, { method: 'POST' });
      const { jobId } = await initRes.json();

      const payload = {
        source: 'stored',
        scrapeEnabled: true,
        extractEnabled: true,
        retrainModels: false,
        generatePdf: true,
      };
      await fetch(`${API_BASE}/api/orchestrator/start-pipeline/${jobId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const es = new EventSource(`${API_BASE}/api/orchestrator/events?jobId=${jobId}`);
      esRef.current = es;
      es.onmessage = (ev) => {
        try {
          const data: StepEvent = JSON.parse(ev.data);
          setEvents((prev) => [...prev, data]);
        } catch {}
      };
      es.onerror = () => closeStream();
    } catch (err) {
      console.error(err);
      alert('Stored-data pipeline failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="btn_border_silver mb-8">
      <div className="card_background rounded p-8">
        <h2 className="text-2xl font-semibold text_defaultColor mb-6">Upload Curriculum PDF</h2>

        <div className="space-y-6">
          {/* Drop area */}
          <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-[var(--brand-teal,#025864)]/50 transition-colors">
            <input
              id="pdf-upload"
              type="file"
              accept=".pdf"
              onChange={(e) => {
                const f = e.target.files?.[0] || null;
                if (f && f.type !== 'application/pdf') return alert('Please upload a PDF file.');
                setFile(f);
              }}
              className="hidden"
            />
            <label htmlFor="pdf-upload" className="cursor-pointer flex flex-col items-center">
              <RiFilePdfLine className="text-6xl mb-4" style={{ color: 'var(--brand-teal,#025864)' }} />
              <p className="text-xl text_defaultColor mb-2">
                {file ? file.name : 'Click to upload PDF file'}
              </p>
              <p className="text_secondaryColor">
                {file ? 'File ready for processing' : 'Drag and drop or click to select your curriculum PDF'}
              </p>
            </label>
          </div>

          {/* Buttons */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <button
              onClick={handleGenerateFromPdf}
              disabled={!file || busy}
              className={`btn_background_purple w-full text-white px-6 py-3 rounded-lg font-semibold text-base transition-all whitespace-nowrap ${
                !file || busy ? 'opacity-50 cursor-not-allowed' : 'hover:shadow-lg hover:scale-[1.01]'
              }`}
            >
              Generate Report
            </button>

            <button
              onClick={handleUseStored}
              disabled={busy}
              className="w-full px-6 py-3 rounded-lg font-semibold text-base transition-all border border-gray-300 hover:bg-gray-100 inline-flex items-center justify-center gap-2 whitespace-nowrap"
              style={{ color: 'var(--brand-teal,#025864)' }}
            >
              <RiPlayListAddLine className="text-xl" />
              Use Stored Data
            </button>
          </div>

          {busy && <p className="text-sm text-gray-500">Processing…</p>}

          {/* Show parsed courses */}
          {parsedRows.length > 0 && (
            <div className="rounded-md p-4 bg-gray-50 border mt-4">
              <p className="font-semibold mb-2">Parsed from PDF:</p>
              <ul className="list-disc ml-5 text-sm">
                {parsedRows.map((r, i) => (
                  <li key={i}>
                    <b>{r.course_code}</b> — {r.course_title}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Show pipeline events */}
          {events.length > 0 && (
            <div className="rounded-md p-4 bg-gray-50 border mt-4">
              <p className="font-semibold mb-2">Pipeline status:</p>
              <ol className="list-decimal ml-5 text-sm space-y-1">
                {events.map((e, idx) => (
                  <li key={idx}>
                    {e.timestamp} — <b>{e.function}</b>: {e.status}{' '}
                    {e.reportUrl && (
                      <a
                        href={e.reportUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="underline text-blue-600"
                      >
                        View Report
                      </a>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
