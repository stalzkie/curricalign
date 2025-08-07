# curricalign
CurricAlign is an intelligent curriculum-to-job alignment system that bridges the gap between academic course content and real-world industry demands. 

## TL;DR: Steps to Connect Dashboard to Real Data

# 1. Setup Supabase
Create project at supabase.com
Run SQL to create 4 tables: courses, job_postings, skills, course_job_alignment

# 2. Create FastAPI Backend
Create main.py with 6 API endpoints
Add .env with Supabase keys

# 3. Populate Database (Manual/Scripted)
Import your course data into courses table
Scrape/import job postings into job_postings table
Run analysis to fill course_job_alignment table

# 4. Update Frontend
Replace mock functions in dataService.ts:

# 5. Run Everything

> # Terminal 1: Start FastAPI
> uvicorn main:app --reload --port 8000
> 
> # Terminal 2: Start Next.js  
> npm run dev

Bottom Line: Database setup + API creation + data import + 6 fetch function updates = Real dashboard with your data instead of mock data.

## /---/---/---/---/

This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
