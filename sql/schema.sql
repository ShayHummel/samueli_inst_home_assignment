-- Simplified clinical schema for assignment Task 3.1 (PostgreSQL).
--
-- Reproduced from the assignment brief. Types are inferred: the brief names the
-- columns but not their types, so the choices below are the conventional ones and
-- are stated as assumptions in results/part3_sql_and_pipeline.md.

CREATE TABLE patients (
    patient_id  integer PRIMARY KEY,
    birth_date  date,
    sex         text
);

CREATE TABLE visits (
    visit_id    integer PRIMARY KEY,
    patient_id  integer NOT NULL REFERENCES patients (patient_id),
    visit_date  date,
    department  text,
    provider_id integer
);

CREATE TABLE diagnoses (
    diagnosis_id integer PRIMARY KEY,
    visit_id     integer NOT NULL REFERENCES visits (visit_id),
    icd10_code   text,
    description  text
);

-- Note the denormalisation: medications carries BOTH patient_id and visit_id.
-- visit_id is nullable so that a prescription not tied to an encounter (e.g. a
-- phone renewal) can still be recorded against the patient.
CREATE TABLE medications (
    med_id     integer PRIMARY KEY,
    patient_id integer NOT NULL REFERENCES patients (patient_id),
    visit_id   integer REFERENCES visits (visit_id),
    drug_name  text,
    start_date date,
    end_date   date,
    dose_mg    numeric
);

CREATE TABLE notes (
    note_id    integer PRIMARY KEY,
    visit_id   integer NOT NULL REFERENCES visits (visit_id),
    note_text  text,
    created_at timestamptz
);

CREATE INDEX visits_patient_date_idx ON visits (patient_id, visit_date);
CREATE INDEX visits_department_date_idx ON visits (department, visit_date);
CREATE INDEX diagnoses_visit_idx ON diagnoses (visit_id);
CREATE INDEX diagnoses_code_idx ON diagnoses (icd10_code);
CREATE INDEX medications_patient_idx ON medications (patient_id);
CREATE INDEX notes_visit_created_idx ON notes (visit_id, created_at DESC);
