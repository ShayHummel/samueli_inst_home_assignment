-- 3.1.5  Some visits have duplicate notes. Return exactly one row per visit: the
--        most recent note by created_at.
--
-- Assumptions
--   * Ties on created_at are broken by the highest note_id, on the reasoning that
--     the later-inserted row is the later note. Without a tie-break the query
--     returns an arbitrary row among ties and is not reproducible -- and duplicate
--     rows carrying identical timestamps is exactly the shape of a double-submit
--     bug, so ties are likely rather than hypothetical here.
--   * Visits with no notes are excluded; the question asks for one row per visit
--     that has notes.
--
-- DISTINCT ON is the idiomatic PostgreSQL form and reads directly as the
-- requirement. It also lets the planner walk the (visit_id, created_at DESC)
-- index rather than materialising a window over every note.

SELECT DISTINCT ON (n.visit_id)
       n.visit_id,
       n.note_id,
       n.created_at,
       n.note_text
FROM notes AS n
ORDER BY n.visit_id, n.created_at DESC, n.note_id DESC;

-- Portable equivalent, for a reviewer who wants standard SQL rather than a
-- PostgreSQL extension:
--
--   SELECT visit_id, note_id, created_at, note_text
--   FROM (
--       SELECT n.*,
--              ROW_NUMBER() OVER (
--                  PARTITION BY n.visit_id
--                  ORDER BY n.created_at DESC, n.note_id DESC
--              ) AS rn
--       FROM notes AS n
--   ) ranked
--   WHERE rn = 1;
