'use client';

import UploadCard from './UploadCard';

export default function ReportView() {
  return (
    <div className="p-8 min-h-screen" style={{ background: 'var(--background)' }}>
      <div className="max-w-7xl mx-auto">
        <h1 className="text-4xl font-bold text_defaultColor mb-6">Generate Report</h1>
        <p className="text-lg text_secondaryColor mb-8">
          Upload your curriculum PDF or run the pipeline using stored data. We’ll parse courses,
          extract skills, evaluate alignment, and generate a downloadable report.
        </p>

        {/* UploadCard is now self-contained: handles scan-pdf, starts the orchestrator,
            shows parsed rows and live pipeline events, and links to the final report. */}
        <UploadCard />
      </div>
    </div>
  );
}
