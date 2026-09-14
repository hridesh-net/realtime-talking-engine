-- `cost_cap` was a value nothing produced: the engine read SESSION_COST_CAP_USD
-- and enforced nothing, so the vocabulary admitted an end reason no code path
-- could yield. Removed 2026-09-13 together with the variable; if a cost meter
-- ever lands, it arrives with its own forward migration re-adding the value.
-- The inline CHECK in 0002 was unnamed, so it carries Postgres's default name.
ALTER TABLE session_ingests DROP CONSTRAINT session_ingests_end_reason_check;
ALTER TABLE session_ingests ADD CONSTRAINT session_ingests_end_reason_check
    CHECK (end_reason IN ('interviewer_ended', 'abandoned', 'duration_cap', 'error'));
