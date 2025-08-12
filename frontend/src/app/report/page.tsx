'use client';

import { useState } from 'react';

interface ProcessStep {
  id: string;
  name: string;
  status: 'pending' | 'in-progress' | 'completed' | 'error';
}

const PROCESS_STEPS: ProcessStep[] = [
  { id: '1', name: 'Scraping', status: 'pending' },
  { id: '2', name: 'Updating Trending Jobs', status: 'pending' },
  { id: '3', name: 'Extracting Course Skills', status: 'pending' },
  { id: '4', name: 'Extracting Job Skills', status: 'pending' },
  { id: '5', name: 'Generating Course Alignment Scores', status: 'pending' },
  { id: '6', name: 'Creating PDF Report', status: 'pending' },
];

export default function Report() {
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processSteps, setProcessSteps] = useState<ProcessStep[]>(PROCESS_STEPS);
  const [isComplete, setIsComplete] = useState(false);
  const [reportUrl, setReportUrl] = useState<string | null>(null);

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file && file.type === 'application/pdf') {
      setUploadedFile(file);
    } else {
      alert('Please upload a PDF file only.');
    }
  };

  const handleGenerateReport = async () => {
    if (!uploadedFile) {
      alert('Please upload a PDF file first.');
      return;
    }

    setIsProcessing(true);
    setIsComplete(false);
    setReportUrl(null);
    
    // Reset all steps to pending
    setProcessSteps(PROCESS_STEPS.map(step => ({ ...step, status: 'pending' })));

    try {
      // TODO: Replace with actual FastAPI endpoint
      for (let i = 0; i < PROCESS_STEPS.length; i++) {
        // Update current step to in-progress
        setProcessSteps(prev => prev.map((step, index) => 
          index === i 
            ? { ...step, status: 'in-progress' }
            : index < i 
              ? { ...step, status: 'completed' }
              : step
        ));

        // Simulate API call delay
        await new Promise(resolve => setTimeout(resolve, 2000));

        // Mark current step as completed
        setProcessSteps(prev => prev.map((step, index) => 
          index === i ? { ...step, status: 'completed' } : step
        ));
      }

      // Process completed
      setIsComplete(true);
      setReportUrl('/api/download-report'); // TODO: Replace with actual download URL
    } catch (error) {
      console.error('Error generating report:', error);
      // Mark current step as error
      setProcessSteps(prev => prev.map(step => 
        step.status === 'in-progress' ? { ...step, status: 'error' } : step
      ));
    } finally {
      setIsProcessing(false);
    }
  };

  const handleCancelProcess = () => {
    setIsProcessing(false);
    setProcessSteps(PROCESS_STEPS.map(step => ({ ...step, status: 'pending' })));
    // TODO: Make API call to cancel backend process
  };

  const getStepIcon = (status: ProcessStep['status']) => {
    switch (status) {
      case 'completed':
        return '✅';
      case 'in-progress':
        return '⏳';
      case 'error':
        return '❌';
      default:
        return '⭕';
    }
  };

  const getStepStatusColor = (status: ProcessStep['status']) => {
    switch (status) {
      case 'completed':
        return 'text-green-600';
      case 'in-progress':
        return 'text-blue-600';
      case 'error':
        return 'text-red-600';
      default:
        return 'text_secondaryColor';
    }
  };

  return (
    <div className="p-8 min-h-screen" style={{ background: 'var(--background)' }}>
      <div className="max-w-4xl mx-auto">
        <h1 className="text-4xl font-bold text_defaultColor mb-6">Generate Report</h1>
        <p className="text-lg text_secondaryColor mb-8">Upload your curriculum PDF and generate a comprehensive alignment report</p>
        
        {!isProcessing && !isComplete && (
          <div className="btn_border_silver mb-8">
            <div className="card_background rounded p-8">
              <h2 className="text-2xl font-semibold text_defaultColor mb-6">Upload Curriculum PDF</h2>
              
              <div className="space-y-6">
                {/* File Upload Area */}
                <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-purple-400 transition-colors">
                  <input
                    type="file"
                    accept=".pdf"
                    onChange={handleFileUpload}
                    className="hidden"
                    id="pdf-upload"
                  />
                  <label htmlFor="pdf-upload" className="cursor-pointer">
                    <div className="text-6xl mb-4">📄</div>
                    <p className="text-xl text_defaultColor mb-2">
                      {uploadedFile ? uploadedFile.name : 'Click to upload PDF file'}
                    </p>
                    <p className="text_secondaryColor">
                      {uploadedFile ? 'File ready for processing' : 'Drag and drop or click to select your curriculum PDF'}
                    </p>
                  </label>
                </div>

                {/* Generate Button */}
                <div className="flex justify-center">
                  <button
                    onClick={handleGenerateReport}
                    disabled={!uploadedFile}
                    className={`btn_background_purple text-white px-8 py-4 rounded-lg font-semibold text-lg transition-all ${
                      !uploadedFile 
                        ? 'opacity-50 cursor-not-allowed' 
                        : 'hover:shadow-lg transform hover:scale-105'
                    }`}
                  >
                    Generate Report
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Processing Steps */}
        {isProcessing && (
          <div className="btn_border_silver mb-8">
            <div className="card_background rounded p-8">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-2xl font-semibold text_defaultColor">Processing Report</h2>
                <button
                  onClick={handleCancelProcess}
                  className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors"
                >
                  Cancel Process
                </button>
              </div>

              <div className="space-y-4">
                {processSteps.map((step, index) => (
                  <div
                    key={step.id}
                    className={`flex items-center space-x-4 p-4 rounded-lg border transition-all ${
                      step.status === 'in-progress' 
                        ? 'bg-blue-50 border-blue-200' 
                        : step.status === 'completed'
                          ? 'bg-green-50 border-green-200'
                          : step.status === 'error'
                            ? 'bg-red-50 border-red-200'
                            : 'bg-gray-50 border-gray-200'
                    }`}
                  >
                    <div className="text-2xl">
                      {getStepIcon(step.status)}
                    </div>
                    <div className="flex-1">
                      <h3 className={`font-semibold ${getStepStatusColor(step.status)}`}>
                        {step.name}
                      </h3>
                      <p className="text-sm text_triaryColor">
                        Step {index + 1} of {processSteps.length}
                      </p>
                    </div>
                    {step.status === 'in-progress' && (
                      <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
                    )}
                  </div>
                ))}
              </div>

              {/* Progress Bar */}
              <div className="mt-6">
                <div className="flex justify-between text-sm text_secondaryColor mb-2">
                  <span>Progress</span>
                  <span>{processSteps.filter(s => s.status === 'completed').length} / {processSteps.length} completed</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-3">
                  <div 
                    className="bg-gradient-to-r from-purple-500 to-purple-600 h-3 rounded-full transition-all duration-500"
                    style={{ 
                      width: `${(processSteps.filter(s => s.status === 'completed').length / processSteps.length) * 100}%` 
                    }}
                  ></div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Completion State */}
        {isComplete && (
          <div className="btn_border_silver mb-8">
            <div className="card_background rounded p-8 text-center">
              <div className="text-6xl mb-4">🎉</div>
              <h2 className="text-3xl font-bold text_defaultColor mb-4">Report Generated Successfully!</h2>
              <p className="text_secondaryColor mb-8">Your curriculum alignment report is ready for download.</p>
              
              <div className="flex justify-center space-x-4">
                <button
                  onClick={() => {
                    // TODO: Implement actual download
                    if (reportUrl) {
                      window.open(reportUrl, '_blank');
                    }
                  }}
                  className="btn_background_purple text-white px-8 py-4 rounded-lg font-semibold text-lg hover:shadow-lg transform hover:scale-105 transition-all"
                >
                  Download PDF Report
                </button>
                <button
                  onClick={() => {
                    setIsComplete(false);
                    setUploadedFile(null);
                    setReportUrl(null);
                  }}
                  className="px-8 py-4 bg-gray-200 text_defaultColor rounded-lg font-semibold text-lg hover:bg-gray-300 transition-colors"
                >
                  Generate Another Report
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
