-- 3.1.5  Some visits have duplicate notes. Return exactly one row per visit: the most
--        recent note by created_at.
--
-- Ties on created_at break to the highest note_id. Not a pedantic detail: rows sharing
-- an identical timestamp are the signature of the double-submit that created the
-- duplicates, so ties are likely rather than hypothetical. Without a tie-break the
-- result is arbitrary and irreproducible.
--
-- Visits with no notes are excluded; the question asks for one row per visit that has
-- notes.

SELECT DISTINCT ON (n.visit_id)
       n.visit_id,
       n.note_id,
       n.created_at,
       n.note_text
FROM notes AS n
ORDER BY n.visit_id, n.created_at DESC, n.note_id DESC;

-- Portable equivalent, in standard SQL rather than a PostgreSQL extension:
--
--   SELECT visit_id, note_id, created_at, note_text
--   FROM (SELECT n.*,
--                ROW_NUMBER() OVER (PARTITION BY n.visit_id
--                                   ORDER BY n.created_at DESC, n.note_id DESC) AS rn
--         FROM notes AS n) ranked
--   WHERE rn = 1;
