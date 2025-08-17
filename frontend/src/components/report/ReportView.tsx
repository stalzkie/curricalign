'use client';

import { useState } from 'react';
import UploadCard from './UploadCard';
import StepsList from './StepsList';
import ProgressBar from './ProgressBar';
import CompletionCard from './CompletionCard';
import { useOrchestrator } from './useOrchestrator';

export default function ReportView() {
  const [file, setFile] = useState<File | null>(null);
  const {
    steps = [], // ✅ default to empty array if undefined
    isProcessing,
    isComplete,
    reportUrl,
    startFromPdf,
    startFromStored,
    cancel
  } = useOrchestrator();

  const completed = steps.filter(s => s.status === 'completed').length;

  return (
    <div className="p-8 min-h-screen" style={{ background: 'var(--background)' }}>
      <div className="max-w-7xl mx-auto">
        <h1 className="text-4xl font-bold text_defaultColor mb-6">Generate Report</h1>
        <p className="text-lg text_secondaryColor mb-8">
          Upload your curriculum PDF or use stored data to generate a comprehensive alignment report.
        </p>

        {!isProcessing && !isComplete && (
          <UploadCard
            file={file}
            onFileChange={(f) => setFile(f)}
            onGenerateFromPdf={() => file ? startFromPdf(file) : undefined}
            onUseStored={startFromStored}
          />
        )}

        {isProcessing && (
          <div className="btn_border_silver mb-8">
            <div className="card_background rounded p-8">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-2xl font-semibold text_defaultColor">Processing Report</h2>
                <button
                  onClick={cancel}
                  className="px-4 py-2 text-white rounded-lg hover:opacity-90 transition-colors"
                  style={{ background: 'var(--brand-teal,#025864)' }}
                >
                  Cancel Process
                </button>
              </div>

              <StepsList steps={steps} />
              <ProgressBar completed={completed} total={steps.length} />
            </div>
          </div>
        )}

        {isComplete && (
          <CompletionCard
            reportUrl={reportUrl}
            onReset={() => {
              window.scrollTo({ top: 0, behavior: 'smooth' });
              location.reload();
            }}
          />
        )}
      </div>
    </div>
  );
}
