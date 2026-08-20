-- 3.1.4  Per department, the average number of diagnoses recorded per visit in 2025.
--
-- The LEFT JOIN is the whole question: visits with ZERO diagnoses must stay in the
-- denominator. An INNER JOIN computes "diagnoses per visit that had a diagnosis" and
-- inflates every department's average. COUNT(d.diagnosis_id) ignores the NULL from a
-- join miss, while COUNT(DISTINCT v.visit_id) still counts the visit.
--
-- The ::numeric cast stops integer division truncating 3/2 to 1.
-- Date range matches query 1.

SELECT v.department,
       COUNT(DISTINCT v.visit_id) AS visits,
       COUNT(d.diagnosis_id)      AS diagnoses,
       ROUND(
           COUNT(d.diagnosis_id)::numeric
           / NULLIF(COUNT(DISTINCT v.visit_id), 0),
           3
       )                          AS avg_diagnoses_per_visit
FROM visits AS v
LEFT JOIN diagnoses AS d ON d.visit_id = v.visit_id
WHERE v.visit_date >= DATE '2025-01-01'
  AND v.visit_date <  DATE '2026-01-01'
GROUP BY v.department
ORDER BY v.department;
