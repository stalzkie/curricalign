/* eslint-disable no-console */
import 'dotenv/config';
import { GoogleGenAI } from '@google/genai';
import { createClient } from '@supabase/supabase-js';

const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY! });
const supaAdmin = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_SERVICE_KEY!, // server-only
  { auth: { persistSession: false } }
);

// ----------------- helpers -----------------

// chunk long texts into ~1.5k chars
function chunkText(txt: string, size = 1500, overlap = 200) {
  const out: string[] = [];
  for (let i = 0; i < txt.length; i += size - overlap) {
    out.push(txt.slice(i, i + size));
  }
  return out;
}

async function embedBatch(chunks: string[]) {
  const res = await ai.models.embedContent({
    model: 'gemini-embedding-001',
    contents: chunks,
    config: {
      taskType: 'RETRIEVAL_DOCUMENT',
      outputDimensionality: 768
    } as any
  });

  if (!res.embeddings) {
    throw new Error('Gemini did not return embeddings for embedBatch');
  }

  return res.embeddings.map(e => e.values as number[]);
}

// optional single-query helper if you reuse here
async function embedQuery(q: string) {
  const res = await ai.models.embedContent({
    model: 'gemini-embedding-001',
    contents: q,
    config: {
      taskType: 'RETRIEVAL_QUERY',
      outputDimensionality: 768
    } as any
  });

  if (!res.embeddings) {
    throw new Error('Gemini did not return embeddings for embedQuery');
  }

  return res.embeddings[0].values as number[];
}

async function upsertDocs(source: string, records: { title?: string; content: string; metadata?: any }[]) {
  for (const r of records) {
    const chunks = chunkText(r.content);
    const vectors = await embedBatch(chunks);
    const rows = chunks.map((c, i) => ({
      source,
      title: r.title ?? null,
      content: c,
      metadata: r.metadata ?? {},
      embedding: vectors[i]
    }));

    const { error } = await supaAdmin.from('carly_documents').insert(rows);
    if (error) throw error;
  }
}

// ----------------- loaders -----------------

async function loadFromJobs() {
  const { data, error } = await supaAdmin.from('jobs').select('id,title,company,description');
  if (error) throw error;
  return (data ?? []).map(j => ({
    title: `[Job] ${j.title} @ ${j.company}`,
    content: `${j.title} at ${j.company}\n\n${j.description ?? ''}`,
    metadata: { table: 'jobs', id: j.id }
  }));
}

async function loadFromCourseAlignment() {
  const { data, error } = await supaAdmin
    .from('course_alignment_scores')
    .select('course_id, score, matched_job_ids');
  if (error) throw error;
  return (data ?? []).map((r: any) => ({
    title: `[Alignment] Course ${r.course_id}`,
    content: `Course ${r.course_id} alignment score: ${r.score}\nMatched jobs: ${JSON.stringify(
      r.matched_job_ids
    )}`,
    metadata: { table: 'course_alignment_scores', course_id: r.course_id }
  }));
}

async function loadFromProcessDocs() {
  const { data, error } = await supaAdmin
    .from('project_docs')
    .select('id,title,body')
    .eq('collection', 'curricalign_process');
  if (error) throw error;
  return (data ?? []).map(d => ({
    title: `[Process] ${d.title}`,
    content: d.body,
    metadata: { table: 'project_docs', id: d.id, collection: 'curricalign_process' }
  }));
}

// ----------------- main -----------------

(async () => {
  console.log('Seeding Carly knowledge…');

  const batches = [
    { source: 'jobs', loader: loadFromJobs },
    { source: 'course_alignment', loader: loadFromCourseAlignment },
    { source: 'process', loader: loadFromProcessDocs }
    // add more loaders: job_skills, course_skills, trending_jobs, warnings, etc.
  ];

  for (const b of batches) {
    const records = await b.loader();
    await upsertDocs(b.source, records);
    console.log(`  ✓ ${b.source} -> ${records.length} records`);
  }

  console.log('Done.');
})();
