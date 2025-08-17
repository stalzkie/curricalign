'use client';

export default function CompletionCard({
  reportUrl,
  onReset,
}: {
  reportUrl: string | null;
  onReset: () => void;
}) {
  return (
    <div className="btn_border_silver mb-8">
      <div className="card_background rounded p-8 text-center">
        <h2 className="text-3xl font-bold text_defaultColor mb-4">Report Generated Successfully!</h2>
        <p className="text_secondaryColor mb-8">Your curriculum alignment report is ready.</p>
        <div className="flex justify-center gap-4">
          <button
            onClick={() => reportUrl && window.open(reportUrl, '_blank')}
            className="btn_background_purple text-white px-8 py-4 rounded-lg font-semibold text-lg hover:shadow-lg transform hover:scale-105 transition-all"
          >
            Download PDF Report
          </button>
          <button
            onClick={onReset}
            className="px-8 py-4 bg-gray-200 text_defaultColor rounded-lg font-semibold text-lg hover:bg-gray-300 transition-colors"
          >
            Generate Another Report
          </button>
        </div>
      </div>
    </div>
  );
}
