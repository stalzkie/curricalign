// types.ts
export type StepStatus = 'pending' | 'in-progress' | 'completed' | 'error';

export interface ProcessStep {
  id: string;
  name: string;
  // Ensure 'fn' matches the exact function names emitted by the backend
  fn: keyof typeof FN_TO_STEP_ID;
  status: StepStatus;
}

// function-name keys emitted by backend orchestrator
export const FN_TO_STEP_ID = {
  scrape_jobs_from_google_jobs: '1',
  // Removed 'compute_trending_jobs' as it's not emitted by the backend orchestrator
  extract_skills_from_jobs: '2',
  extract_subject_skills_from_supabase: '3',
  retrain_ml_models: '4', // Added this to match backend
  compute_subject_scores_and_save: '5',
  final_checking: '6',
  generate_pdf_report: '7',
} as const;

export type OrchestratorSource = 'stored' | 'pdf';
