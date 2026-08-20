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
-- Shape: compute first-visit-per-patient once with DISTINCT ON, then LEFT JOIN it
-- onto `patients`. The LEFT JOIN is what preserves patients with no visits at all.
--
-- CAUTION, TWO UNRELATED USES OF THE WORD "ON" APPEAR BELOW:
--
--   1. `SELECT DISTINCT ON (v.patient_id)` -- part of the name of PostgreSQL's
--      `DISTINCT ON` operator. It takes a list of EXPRESSIONS to deduplicate by,
--      not a join predicate: "keep only the first row of each group of rows having
--      the same v.patient_id". Nothing is being joined here.
--   2. `... ON first_visit.patient_id = p.patient_id` -- an ordinary join
--      condition, matching the derived table back onto `patients`.
--
-- `DISTINCT ON` is only meaningful together with `ORDER BY`, because "the first
-- row of each group" is defined by that ordering. PostgreSQL therefore requires
-- the LEADING `ORDER BY` expressions to match the `DISTINCT ON` expressions, and
-- rejects the query otherwise with:
--
--     SELECT DISTINCT ON expressions must match initial ORDER BY expressions
--
-- So `ORDER BY v.patient_id, v.visit_date, v.visit_id` is load-bearing in all
-- three positions: `patient_id` first to satisfy that rule, then `visit_date`
-- ascending to make "first row" mean *earliest visit*, then `visit_id` as the
-- deterministic tie-break. Flip `visit_date` to DESC and this silently returns
-- each patient's LATEST visit instead -- that part is not protected by the parser,
-- so the ordering is asserted by test.
--
-- `v.patient_id` is selected as well as deduplicated on, because the outer join
-- needs it as its right-hand key.

SELECT p.patient_id,
       first_visit.visit_date AS first_visit_date,
       first_visit.department AS first_visit_department
FROM patients AS p
LEFT JOIN (
    SELECT DISTINCT ON (v.patient_id)        -- "one row per patient", not a join
           v.patient_id,
           v.visit_date,
           v.department
    FROM visits AS v
    ORDER BY v.patient_id,                   -- required to match DISTINCT ON
             v.visit_date,                   -- ascending => earliest visit wins
             v.visit_id                      -- deterministic tie-break
) AS first_visit ON first_visit.patient_id = p.patient_id   -- this ON is the join
ORDER BY p.patient_id;


-- ---------------------------------------------------------------------------
-- Equivalent LATERAL formulation, and why it is NOT the primary here
-- ---------------------------------------------------------------------------
--
--   SELECT p.patient_id,
--          fv.visit_date AS first_visit_date,
--          fv.department AS first_visit_department
--   FROM patients AS p
--   LEFT JOIN LATERAL (
--       SELECT v.visit_date, v.department
--       FROM visits AS v
--       WHERE v.patient_id = p.patient_id     -- correlation MUST be here
--       ORDER BY v.visit_date, v.visit_id
--       LIMIT 1
--   ) AS fv ON TRUE
--   ORDER BY p.patient_id;
--
-- LATERAL makes a FROM-clause subquery *correlated*: instead of being evaluated
-- once, it is evaluated once per row of the table to its left and may reference
-- that row's columns. It is SQL's for-each loop. `ON TRUE` is filler -- the
-- grammar requires an ON for a LEFT JOIN, but the correlation already happened
-- inside, so there is nothing left to match on.
--
-- The correlation cannot be moved to the ON clause, and unlike the DISTINCT ON /
-- ORDER BY coupling above, that mistake is SILENT rather than an error. `LIMIT 1`
-- has to apply *per patient*; inside the WHERE it does. Moved to ON, the subquery
-- is no longer correlated, so it returns ONE row globally -- the single earliest
-- visit in the entire table -- which is then matched against each patient. Every
-- patient except that one gets NULLs, and the query looks like it worked. Verified
-- on a real cluster: with visits for patients 1 and 2, the ON form drops patient
-- 2's visit entirely.
--
-- Both forms are correct and return identical results; a test asserts that.
-- DISTINCT ON is the primary because it reads conventionally (the join predicate
-- is in ON, where a reader expects it) and matches the idiom already used in
-- query 5.
--
-- The trade-off, stated rather than hidden: DISTINCT ON scans and sorts all of
-- `visits` once, whereas LATERAL performs one index probe per patient. On a large
-- `visits` table with comparatively few patients, LATERAL wins; where most
-- patients have visits, the single pass is competitive or better. If this query
-- ever became hot on a large table, LATERAL is the optimisation to reach for --
-- with the WHERE clause left where it is.
