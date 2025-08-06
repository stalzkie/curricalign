from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class JobBase(BaseModel):
    title: str
    company: str
    location: Optional[str]
    description: Optional[str]
    requirements: Optional[str]
    source: Optional[str]
    via: Optional[str]
    job_id: str
    url: str
    matched_keyword: Optional[str]
    posted_at: Optional[datetime]
    scraped_at: Optional[datetime]

class JobInsertRequest(JobBase):
    pass

class JobResponse(JobBase):
    id: int  # Supabase row ID or UUID
