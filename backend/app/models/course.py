from pydantic import BaseModel
from typing import List, Optional

class CourseBase(BaseModel):
    course_code: str
    course_title: str
    course_description: Optional[str]

class CourseSkillMapping(BaseModel):
    course_id: int
    course_skills: List[str]

class CourseScore(BaseModel):
    course_id: int
    alignment_score: float
    coverage: float
    avg_similarity: float
    matched_job_skill_ids: List[str]
