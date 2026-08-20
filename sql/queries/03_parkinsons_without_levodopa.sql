-- 3.1.3  Patients with a Parkinson's diagnosis (ICD-10 G20) who were never prescribed
--        a levodopa-containing drug.
--
-- Assumptions
--   * LIKE 'G20%' rather than = 'G20'. ICD-10-CM FY2024 split G20 into G20.A1/A2,
--     G20.B1/B2 and G20.C and retired the bare code, so an exact match returns nothing
--     on that vintage. WHO ICD-10 has no G20 children, where exact match would be
--     right. The prefix is correct under both, and under dotless storage ('G20A1').
--     No real ICD-10 code shares the prefix, so it cannot over-match. Costs something:
--     a prefix LIKE cannot use a default-collation btree, hence the text_pattern_ops
--     index in schema.sql (measured: 3x the plan cost without it).
--   * "Never" spans the whole medication record, not only G20-coded visits.
--   * Joined via medications.patient_id, so prescriptions with a NULL visit_id count.
--
-- Known limitation: '%levodopa%' matches 'Carbidopa-Levodopa' and
-- 'levodopa/benserazide' but NOT brand names (Sinemet, Madopar, Rytary), so the query
-- OVER-reports -- a treated patient can appear untreated. Production would resolve
-- drug_name against RxNorm ingredients or ATC N04BA. A test pins the current behaviour
-- so a future switch cannot leave this note stale.

SELECT DISTINCT p.patient_id
FROM patients AS p
JOIN visits    AS v ON v.patient_id = p.patient_id
JOIN diagnoses AS d ON d.visit_id   = v.visit_id
WHERE d.icd10_code LIKE 'G20%'          -- prefix, not '=': see the note above
  AND NOT EXISTS (
      SELECT 1
      FROM medications AS m
      WHERE m.patient_id = p.patient_id
        AND m.drug_name ILIKE '%levodopa%'
  )
ORDER BY p.patient_id;
