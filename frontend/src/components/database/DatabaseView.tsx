'use client';

import { useState } from "react";
import DatabaseNav from "./DatabaseNav";
import CRUDTableViewer from "./TableViewer";
import ReportsViewer from "./ReportsViewer";

export default function DatabaseView() {
  const [active, setActive] = useState("courses");

  const TABLE_COLUMNS: { [key: string]: string[] } = {
    courses: ["id", "course_code", "course_title", "course_description", "created_at"],
    jobs: ["id", "title", "company", "location", "description", "via", "scraped_at"],
    job_skills: ["id", "title", "company", "job_skills", "date_extracted_jobs"],
    course_skills: ["id", "course_code", "course_title", "course_skills", "date_extracted_course"],
    course_alignment_scores: [
      "id",
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

  return (
    <div className="p-4">
      <DatabaseNav active={active} onChange={setActive} />

      {active === "reports" ? (
        <ReportsViewer />
      ) : (
        <CRUDTableViewer tableName={active} columns={TABLE_COLUMNS[active]} />
      )}
    </div>
  );
}
