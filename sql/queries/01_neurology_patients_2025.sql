-- 3.1.1  Count the distinct patients with at least one Neurology visit during 2025.
--
-- Assumes `department` holds exactly 'Neurology'. Matched exactly rather than with
-- ILIKE '%neurolog%', which would also capture 'Neurosurgery'.
--
-- Half-open range rather than BETWEEN '2025-01-01' AND '2025-12-31': stays correct if
-- visit_date is ever widened to a timestamp, and remains index-sargable.

SELECT COUNT(DISTINCT v.patient_id) AS neurology_patients_2025
FROM visits AS v
WHERE v.department = 'Neurology'
  AND v.visit_date >= DATE '2025-01-01'
  AND v.visit_date <  DATE '2026-01-01';
