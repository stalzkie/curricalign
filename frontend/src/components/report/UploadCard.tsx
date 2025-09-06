'use client';

import React from 'react';
import { RiFilePdfLine, RiPlayListAddLine } from 'react-icons/ri';

export type UploadCardProps = {
  file: File | null;
  onFileChange: (f: File | null) => void;
  onGenerateFromPdf: () => void | Promise<void>;
  onUseStored: () => void | Promise<void>;
  /** Optional: disable buttons while processing */
  disabled?: boolean;
};

export default function UploadCard({
  file,
  onFileChange,
  onGenerateFromPdf,
  onUseStored,
  disabled = false,
}: UploadCardProps) {
  const isGenerateDisabled = disabled || !file;

  return (
    <div className="btn_border_silver mb-8">
      <div className="card_background rounded p-8">
        <h2 className="text-2xl font-semibold text_defaultColor mb-6">
          Upload Curriculum PDF
        </h2>

        <div className="space-y-6">
          {/* Drop area */}
          <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-[var(--brand-teal,#025864)]/50 transition-colors">
            <input
              id="pdf-upload"
              type="file"
              accept="application/pdf,.pdf"
              onChange={(e) => {
                const f = e.currentTarget.files?.[0] || null;
                if (f && f.type !== 'application/pdf') {
                  alert('Please upload a PDF file.');
                  e.currentTarget.value = '';
                  return;
                }
                onFileChange(f);
              }}
              className="hidden"
            />
            <label htmlFor="pdf-upload" className="cursor-pointer flex flex-col items-center">
              <RiFilePdfLine
                className="text-6xl mb-4"
                style={{ color: 'var(--brand-teal,#025864)' }}
              />
              <p className="text-xl text_defaultColor mb-2">
                {file ? file.name : 'Click to upload PDF file'}
              </p>
              <p className="text_secondaryColor">
                {file ? 'File ready for processing' : 'Drag and drop or click to select your curriculum PDF'}
              </p>
            </label>
          </div>

          {/* Buttons: equal width, responsive */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <button
              onClick={onGenerateFromPdf}
              disabled={isGenerateDisabled}
              className={`btn_background_purple w-full text-white px-6 py-3 rounded-lg font-semibold text-base transition-all whitespace-nowrap ${
                isGenerateDisabled ? 'opacity-50 cursor-not-allowed' : 'hover:shadow-lg hover:scale-[1.01]'
              }`}
            >
              Generate Report
            </button>

            <button
              onClick={onUseStored}
              disabled={disabled}
              className={`w-full px-6 py-3 rounded-lg font-semibold text-base transition-all border border-gray-300 inline-flex items-center justify-center gap-2 whitespace-nowrap ${
                disabled ? 'opacity-50 cursor-not-allowed' : 'hover:bg-gray-100'
              }`}
              style={{ color: 'var(--brand-teal,#025864)' }}
            >
              <RiPlayListAddLine className="text-xl" />
              Use Stored Data
            </button>
          </div>

          {/* Notice */}
          <div className="rounded-md p-4 bg-[rgba(2,88,100,0.06)] border border-[rgba(2,88,100,0.18)]">
            <p className="text-sm" style={{ color: 'var(--brand-teal,#025864)' }}>
              “Use Stored Data” will run the orchestrator using information already in your database,
              including previously stored curriculum data.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
