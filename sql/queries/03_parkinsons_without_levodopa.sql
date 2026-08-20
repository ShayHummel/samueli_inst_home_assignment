-- 3.1.3  Patients with a Parkinson's diagnosis (ICD-10 G20) who were never prescribed
--        a levodopa-containing drug.
--
-- Assumptions
--   * LIKE 'G20%' rather than = 'G20': ICD-10-CM added subcodes (G20.A1, G20.B2, ...)
--     in FY2024. No sibling code shares the prefix, so this cannot over-match.
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
WHERE d.icd10_code LIKE 'G20%'
  AND NOT EXISTS (
      SELECT 1
      FROM medications AS m
      WHERE m.patient_id = p.patient_id
        AND m.drug_name ILIKE '%levodopa%'
  )
ORDER BY p.patient_id;
