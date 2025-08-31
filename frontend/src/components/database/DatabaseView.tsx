'use client';

import { useState, useMemo } from "react";
import DatabaseNav from "./DatabaseNav";
import CRUDTableViewer from "./TableViewer";

export default function DatabaseView() {
  const [active, setActive] = useState("courses");

  // IMPORTANT: Make sure DatabaseNav.TABLES contains exactly these keys.
  const TABLE_COLUMNS: { [key: string]: string[] } = {
    courses: ["course_id", "course_code", "course_title", "course_description", "created_at"],
    jobs: ["job_id", "title", "company", "location", "description", "via", "scraped_at"],
    job_skills: ["job_skill_id", "title", "company", "job_skills", "date_extracted_jobs"],
    course_skills: ["course_skill_id", "course_code", "course_title", "course_skills", "date_extracted_course"],
    course_alignment_scores_clean: [
      "course_alignment_score_clean_id",
      "course_code",
      "course_title",
      "skills_taught",
      "skills_in_market",
      "score",
      "coverage",
      "avg_similarity",
      "calculated_at",
    ],
  };

  // Defensive: avoid passing undefined columns to the viewer
  const columnsForActive = useMemo(() => TABLE_COLUMNS[active], [active]);

  return (
    <div className="p-4">
      <DatabaseNav active={active} onChange={setActive} />

      {!columnsForActive ? (
        <div className="mt-4 rounded border border-red-300 bg-red-50 p-4 text-sm text-red-800">
          No column configuration found for <b>{active}</b>. Make sure this key exists in <code>TABLE_COLUMNS</code>
          and in your navigation.
        </div>
      ) : (
        <CRUDTableViewer tableName={active} columns={columnsForActive} />
      )}
    </div>
  );
}
