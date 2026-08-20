-- 3.1.4  Per department, compute the average number of diagnoses recorded per
--        visit in 2025.
--
-- Assumptions
--   * Visits with ZERO diagnoses are part of the denominator. This is the crux of
--     the question: an INNER JOIN would drop them, inflating every average, since
--     it would compute "diagnoses per visit that had a diagnosis". The LEFT JOIN
--     keeps the visit and contributes 0 to the numerator.
--   * A visit is attributed to the department recorded on the visit row.
--   * 2025 filters on visit_date, matching query 1.
--
-- COUNT(d.diagnosis_id) counts non-NULL values, so a LEFT JOIN miss adds nothing
-- to the numerator while COUNT(DISTINCT v.visit_id) still counts the visit. The
-- ::numeric cast avoids integer division silently truncating 3/2 to 1.

SELECT v.department,
       COUNT(DISTINCT v.visit_id)                          AS visits,
       COUNT(d.diagnosis_id)                               AS diagnoses,
       ROUND(
           COUNT(d.diagnosis_id)::numeric
           / NULLIF(COUNT(DISTINCT v.visit_id), 0),
           3
       )                                                   AS avg_diagnoses_per_visit
FROM visits AS v
LEFT JOIN diagnoses AS d ON d.visit_id = v.visit_id
WHERE v.visit_date >= DATE '2025-01-01'
  AND v.visit_date <  DATE '2026-01-01'
GROUP BY v.department
ORDER BY v.department;
