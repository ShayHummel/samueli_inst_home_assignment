-- 3.1.2  For every patient, return the date of their first-ever visit and the
--        department of that visit.
--
-- Assumptions
--   * "every patient" is read literally: a patient with no visits at all still
--     appears, with NULLs. A plain GROUP BY over `visits` would silently drop
--     them, which quietly changes the question from "every patient" to "every
--     patient who has visited".
--   * Ties on visit_date are broken by the lower visit_id, so the result is
--     deterministic. Without a tie-break, two visits on the same date make the
--     returned department arbitrary and the query non-reproducible -- the same
--     concern as Part 2.6.
--
-- LEFT JOIN LATERAL ... LIMIT 1 lets the planner stop at the first row per
-- patient using the (patient_id, visit_date) index, rather than sorting every
-- visit the patient ever had.

SELECT p.patient_id,
       first_visit.visit_date AS first_visit_date,
       first_visit.department AS first_visit_department
FROM patients AS p
LEFT JOIN LATERAL (
    SELECT v.visit_date,
           v.department
    FROM visits AS v
    WHERE v.patient_id = p.patient_id
    ORDER BY v.visit_date, v.visit_id
    LIMIT 1
) AS first_visit ON TRUE
ORDER BY p.patient_id;

-- Variant, if only patients who have actually visited are wanted. Shorter, and
-- usually marginally faster on a small table, but it answers a subtly different
-- question:
--
--   SELECT DISTINCT ON (v.patient_id)
--          v.patient_id, v.visit_date AS first_visit_date, v.department
--   FROM visits AS v
--   ORDER BY v.patient_id, v.visit_date, v.visit_id;
