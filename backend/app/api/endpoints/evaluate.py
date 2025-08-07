from fastapi import APIRouter
from ...services.evaluator import compute_subject_scores_and_save

router = APIRouter()

@router.post("/run")
def evaluate_subject_scores():
    report = compute_subject_scores_and_save()
    return {"message": "Evaluation complete", "report": report}
