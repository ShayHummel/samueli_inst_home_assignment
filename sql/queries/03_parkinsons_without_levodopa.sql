-- 3.1.3  Find patients with a Parkinson's diagnosis (ICD-10 G20) who were never
--        prescribed a levodopa-containing drug.
--
-- Assumptions
--   * `LIKE 'G20%'` rather than `= 'G20'`. ICD-10-CM expanded G20 into subcodes
--     (G20.A1, G20.B2, ...) from FY2024, so an exact match silently misses
--     patients coded under the newer scheme. The prefix match accepts both.
--     Note G20 has no sibling codes sharing the prefix, so this cannot over-match.
--   * "never prescribed" is evaluated over the patient's whole medication record,
--     not just visits where G20 was coded -- a levodopa course predating the
--     diagnosis still means the patient was prescribed it.
--   * The link is `medications.patient_id`, not `medications.visit_id`, so
--     prescriptions with a NULL visit_id (renewals outside an encounter) still count.
--
-- Known limitation, stated rather than hidden: '%levodopa%' is a string match on
-- the drug name. It catches 'Levodopa', 'carbidopa-levodopa' and
-- 'levodopa/benserazide', but NOT brand names such as 'Sinemet', 'Madopar' or
-- 'Rytary'. A production version would resolve drug_name against a terminology
-- (RxNorm ingredient, or ATC N04BA) instead of matching substrings. As written,
-- the query over-reports: a patient on Sinemet appears as never treated.

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
