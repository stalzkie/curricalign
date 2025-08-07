from fastapi import APIRouter
from ...services.query_generator import get_top_keywords

router = APIRouter()

@router.get("/top")
def fetch_top_keywords(n: int = 20):
    top_keywords = get_top_keywords(n)
    return {"keywords": top_keywords}
