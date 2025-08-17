'use client';

import { useEffect, useState } from "react";

export default function ReportsViewer() {
  const [files, setFiles] = useState<string[]>([]);

  useEffect(() => {
    // Requires backend to serve index.json (list of report files)
    fetch("/static/reports/index.json")
      .then((res) => res.json())
      .then((data) => setFiles(data))
      .catch(() => setFiles([]));
  }, []);

  return (
    <div className="btn_border_silver">
      <div className="card_background rounded p-6">
        <h2 className="text-xl font-bold text_defaultColor mb-4">
          Generated Reports
        </h2>

        {files.length === 0 ? (
          <p className="text_secondaryColor text-sm">No reports found.</p>
        ) : (
          <ul className="divide-y divide-gray-200/50">
            {files.map((filename, i) => (
              <li
                key={filename}
                className={`flex justify-between items-center py-3 px-2 transition-colors ${
                  i % 2 === 0 ? "bg-white" : "bg-gray-50"
                } hover:bg-gray-100 rounded`}
              >
                <span className="text_defaultColor font-medium">
                  {filename}
                </span>
                <a
                  href={`/static/reports/${filename}`}
                  download
                  className="px-3 py-1.5 rounded-md text-sm font-medium border border-[var(--foreground,#111827)]/20 text_defaultColor hover:bg-black/5 transition"
                >
                  Download
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
