from pydantic import BaseModel
from typing import List

class EvaluationRequest(BaseModel):
    course_ids: List[int]  # Or course_codes
    model_name: str  # e.g., "subject_success_model"

class EvaluationResult(BaseModel):
    course_id: int
    score: float
    coverage: float
    matched_skills: List[str]
