// constants.ts
import type { ProcessStep } from './types';

const DEFAULT_API_BASE = 'http://localhost:8000';
export const API_BASE =
  (process.env.NEXT_PUBLIC_API_BASE || DEFAULT_API_BASE).replace(/\/$/, '');

// New endpoint to initialize a job and get a jobId
export const ORCHESTRATOR_INIT_URL   = `${API_BASE}/api/orchestrator/init`;
// Modified endpoint to explicitly start the pipeline for a given jobId
export const ORCHESTRATOR_START_PIPELINE_URL = `${API_BASE}/api/orchestrator/start-pipeline`;

export const ORCHESTRATOR_CANCEL_URL = '/api/orchestrator/cancel';
export const ORCHESTRATOR_EVENTS_URL = `${API_BASE}/api/orchestrator/events`;
export const ORCHESTRATOR_STATUS_URL = `${API_BASE}/api/orchestrator/status`;
export const PDF_UPLOAD_URL = '/api/scan-pdf'; // <-- must match FastAPI router

// Pipeline steps in display order
export const INITIAL_STEPS: ProcessStep[] = [
  { id: '1', name: 'Scraping Jobs', fn: 'scrape_jobs_from_google_jobs', status: 'pending' },
  { id: '2', name: 'Extracting Job Skills', fn: 'extract_skills_from_jobs', status: 'pending' },
  { id: '3', name: 'Extracting Course Skills', fn: 'extract_subject_skills_from_supabase', status: 'pending' },
  { id: '4', name: 'Retraining ML Models', fn: 'retrain_ml_models', status: 'pending' },
  { id: '5', name: 'Generating Course Alignment Scores', fn: 'compute_subject_scores_and_save', status: 'pending' },
  { id: '6', name: 'Final Validation', fn: 'final_checking', status: 'pending' },
  { id: '7', name: 'Creating PDF Report', fn: 'generate_pdf_report', status: 'pending' },
];
