# FastAPI Backend Setup with Supabase

This document outlines how to set up the FastAPI backend to work with your dashboard.

## Required Dependencies

```bash
pip install fastapi uvicorn supabase python-dotenv
```

## Environment Variables (.env)

```
SUPABASE_URL=your_supabase_project_url
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
```

## API Endpoints Structure

### 1. Skills Endpoints
- `GET /api/skills/most-demanded` - Returns top 10 most in-demand skills
- `GET /api/skills/missing` - Returns list of missing skills

### 2. Courses Endpoints
- `GET /api/courses/top-matching` - Returns courses with highest job market alignment
- `GET /api/courses/warnings` - Returns courses with low matching percentages

### 3. Jobs Endpoints
- `GET /api/jobs/in-demand` - Returns top 10 most in-demand jobs

### 4. Dashboard Endpoints
- `GET /api/dashboard/kpi` - Returns KPI metrics

## Database Schema (Supabase Tables)

### courses
```sql
CREATE TABLE courses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_name TEXT NOT NULL,
    course_code TEXT UNIQUE NOT NULL,
    description TEXT,
    skills JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### job_postings
```sql
CREATE TABLE job_postings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    required_skills JSONB,
    company TEXT,
    location TEXT,
    posted_date TIMESTAMP,
    scraped_at TIMESTAMP DEFAULT NOW()
);
```

### skills
```sql
CREATE TABLE skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    category TEXT,
    demand_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### course_job_alignment
```sql
CREATE TABLE course_job_alignment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id UUID REFERENCES courses(id),
    job_posting_id UUID REFERENCES job_postings(id),
    alignment_score DECIMAL(5,2),
    matched_skills JSONB,
    missing_skills JSONB,
    analyzed_at TIMESTAMP DEFAULT NOW()
);
```

## Sample FastAPI Implementation

```python
# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="CurricAlign API")

# CORS middleware for frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Your Next.js app
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase client
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_ANON_KEY")
)

@app.get("/api/skills/most-demanded")
async def get_most_demanded_skills():
    # Query your skills table ordered by demand_count
    response = supabase.table("skills").select("name, demand_count").order("demand_count", desc=True).limit(10).execute()
    return response.data

@app.get("/api/courses/top-matching")
async def get_top_matching_courses():
    # Query courses with their average alignment scores
    response = supabase.rpc("get_courses_with_avg_alignment").execute()
    return response.data

@app.get("/api/jobs/in-demand")
async def get_in_demand_jobs():
    # Query job postings grouped by title
    response = supabase.rpc("get_job_demand_stats").execute()
    return response.data

@app.get("/api/dashboard/kpi")
async def get_kpi_data():
    # Calculate KPI metrics
    courses_count = supabase.table("courses").select("id", count="exact").execute()
    jobs_count = supabase.table("job_postings").select("id", count="exact").execute()
    skills_count = supabase.table("skills").select("id", count="exact").execute()
    avg_alignment = supabase.rpc("get_average_alignment_score").execute()
    
    return {
        "averageAlignmentScore": avg_alignment.data[0]["avg_score"],
        "totalSubjectsAnalyzed": courses_count.count,
        "totalJobPostsAnalyzed": jobs_count.count,
        "skillsExtracted": skills_count.count
    }
```

## Required Database Functions

```sql
-- Function to get courses with average alignment scores
CREATE OR REPLACE FUNCTION get_courses_with_avg_alignment()
RETURNS TABLE (
    course_name TEXT,
    course_code TEXT,
    avg_alignment_score DECIMAL
)
LANGUAGE sql
AS $$
    SELECT 
        c.course_name,
        c.course_code,
        ROUND(AVG(cja.alignment_score), 2) as avg_alignment_score
    FROM courses c
    JOIN course_job_alignment cja ON c.id = cja.course_id
    GROUP BY c.id, c.course_name, c.course_code
    ORDER BY avg_alignment_score DESC;
$$;

-- Function to get job demand statistics
CREATE OR REPLACE FUNCTION get_job_demand_stats()
RETURNS TABLE (
    title TEXT,
    demand_count BIGINT
)
LANGUAGE sql
AS $$
    SELECT 
        title,
        COUNT(*) as demand_count
    FROM job_postings
    GROUP BY title
    ORDER BY demand_count DESC
    LIMIT 10;
$$;

-- Function to get average alignment score
CREATE OR REPLACE FUNCTION get_average_alignment_score()
RETURNS TABLE (avg_score DECIMAL)
LANGUAGE sql
AS $$
    SELECT ROUND(AVG(alignment_score), 1) as avg_score
    FROM course_job_alignment;
$$;
```

## Running the Backend

```bash
# In your backend directory
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000` with automatic docs at `http://localhost:8000/docs`.

## Next Steps

1. Set up your Supabase project
2. Create the database tables using the provided schema
3. Implement the FastAPI endpoints
4. Update the frontend dataService.ts to use real API calls instead of mock data
5. Run both frontend (port 3000) and backend (port 8000) simultaneously
