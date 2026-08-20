-- 3.1.2  For every patient, the date of their first-ever visit and its department.
--
-- "Every patient" read literally: a patient with no visits appears with NULLs. Hence
-- the LEFT JOIN -- a GROUP BY over `visits` would drop them and silently answer
-- "every patient who has visited".
--
-- Two unrelated uses of "ON" below. `DISTINCT ON (...)` names PostgreSQL's
-- deduplication operator and takes a list of expressions, not a predicate; the
-- trailing ON is the join condition.
--
-- The ORDER BY is load-bearing in all three positions:
--   patient_id  required -- DISTINCT ON expressions must match the leading ORDER BY,
--               and PostgreSQL rejects the query otherwise
--   visit_date  ascending, so "first row per group" means EARLIEST visit. DESC is
--               valid SQL and silently returns the latest instead, so it is tested
--   visit_id    deterministic tie-break for two visits on the same date

SELECT p.patient_id,
       first_visit.visit_date AS first_visit_date,
       first_visit.department AS first_visit_department
FROM patients AS p
LEFT JOIN (
    SELECT DISTINCT ON (v.patient_id)
           v.patient_id,
           v.visit_date,
           v.department
    FROM visits AS v
    ORDER BY v.patient_id, v.visit_date, v.visit_id
) AS first_visit ON first_visit.patient_id = p.patient_id
ORDER BY p.patient_id;

-- Equivalent LATERAL form, faster on a large `visits` table since it probes an index
-- once per patient instead of sorting every row:
--
--   LEFT JOIN LATERAL (
--       SELECT v.visit_date, v.department
--       FROM visits AS v
--       WHERE v.patient_id = p.patient_id      -- must be HERE, not in the ON clause
--       ORDER BY v.visit_date, v.visit_id
--       LIMIT 1
--   ) AS fv ON TRUE
--
-- LATERAL evaluates the subquery once per left-hand row and lets it reference that
-- row's columns; `ON TRUE` is filler. That WHERE fails SILENTLY if moved to ON: the
-- subquery de-correlates, returns the single earliest visit in the whole table, and
-- every other patient loses theirs. Both correct forms are tested against each other,
-- and so is the broken one.
