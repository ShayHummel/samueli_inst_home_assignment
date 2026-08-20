-- 3.1.1  Count the distinct patients with at least one Neurology visit during 2025.
--
-- Assumptions
--   * `department` holds the exact string 'Neurology'. If departments are entered
--     free-text in practice, swap the predicate for
--     `v.department ILIKE '%neurolog%'` -- but that also matches 'Neurosurgery',
--     so the exact match is the safer default and the messy case is a data-quality
--     question for the source system, not something to paper over in SQL.
--   * "during 2025" means the visit_date falls in calendar 2025.
--
-- The half-open range is deliberate: it is sargable (an index on visit_date is
-- usable), and it stays correct if visit_date is ever widened to a timestamp,
-- where `BETWEEN '2025-01-01' AND '2025-12-31'` would silently drop 31 December
-- after midnight.

SELECT COUNT(DISTINCT v.patient_id) AS neurology_patients_2025
FROM visits AS v
WHERE v.department = 'Neurology'
  AND v.visit_date >= DATE '2025-01-01'
  AND v.visit_date <  DATE '2026-01-01';
