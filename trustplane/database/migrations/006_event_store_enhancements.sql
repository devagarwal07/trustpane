-- =====================================================
-- Migration 006: Event Store Enhancements
-- Purpose: Optimize events table for hash-chained event sourcing
-- =====================================================

-- Add indexes for event store performance
-- Index for stream lookups with version ordering
CREATE INDEX IF NOT EXISTS idx_events_stream_version 
ON events (org_id, stream_id, version);

-- Index for idempotency key lookups
CREATE INDEX IF NOT EXISTS idx_events_idempotency 
ON events (org_id, idempotency_key) 
WHERE idempotency_key IS NOT NULL;

-- Index for event type queries
CREATE INDEX IF NOT EXISTS idx_events_type 
ON events (org_id, event_type, occurred_at DESC);

-- Index for hash chain verification
CREATE INDEX IF NOT EXISTS idx_events_hash_chain 
ON events (org_id, stream_id, previous_hash);

-- =====================================================
-- Constraints for Hash Chain Integrity
-- =====================================================

-- Ensure version is always positive
ALTER TABLE events 
ADD CONSTRAINT events_version_positive 
CHECK (version > 0);

-- Ensure hash is always present and valid length (SHA-256 = 64 hex chars)
ALTER TABLE events 
ADD CONSTRAINT events_hash_length 
CHECK (length(hash) = 64);

-- Ensure previous_hash is always present and valid length
ALTER TABLE events 
ADD CONSTRAINT events_previous_hash_length 
CHECK (length(previous_hash) = 64);

-- Unique constraint on idempotency key per org (for idempotent writes)
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_idempotency_unique 
ON events (org_id, idempotency_key) 
WHERE idempotency_key IS NOT NULL;

-- Unique constraint on stream_id + version (prevent version conflicts)
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_stream_version_unique 
ON events (org_id, stream_id, version);

-- =====================================================
-- Function: Validate Hash Chain on Insert
-- =====================================================

CREATE OR REPLACE FUNCTION validate_event_hash_chain()
RETURNS TRIGGER AS $$
DECLARE
    latest_event RECORD;
    expected_prev_hash TEXT;
    genesis_hash TEXT := '0000000000000000000000000000000000000000000000000000000000000000';
BEGIN
    -- Get the latest event in this stream
    SELECT * INTO latest_event
    FROM events
    WHERE org_id = NEW.org_id
      AND stream_id = NEW.stream_id
    ORDER BY version DESC
    LIMIT 1;
    
    -- Determine expected previous hash
    IF latest_event.id IS NULL THEN
        -- First event in stream
        expected_prev_hash := genesis_hash;
        
        -- Version must be 1
        IF NEW.version != 1 THEN
            RAISE EXCEPTION 'First event must have version 1, got %', NEW.version;
        END IF;
    ELSE
        -- Subsequent event
        expected_prev_hash := latest_event.hash;
        
        -- Version must be sequential
        IF NEW.version != latest_event.version + 1 THEN
            RAISE EXCEPTION 'Version gap: expected %, got %', 
                latest_event.version + 1, NEW.version;
        END IF;
    END IF;
    
    -- Validate previous_hash matches
    IF NEW.previous_hash != expected_prev_hash THEN
        RAISE EXCEPTION 'Invalid previous_hash: expected %, got %',
            substring(expected_prev_hash, 1, 16) || '...',
            substring(NEW.previous_hash, 1, 16) || '...';
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger (run BEFORE insert to validate)
DROP TRIGGER IF EXISTS tr_validate_event_hash_chain ON events;
CREATE TRIGGER tr_validate_event_hash_chain
    BEFORE INSERT ON events
    FOR EACH ROW
    EXECUTE FUNCTION validate_event_hash_chain();

-- =====================================================
-- Function: Get Stream Integrity Report
-- =====================================================

CREATE OR REPLACE FUNCTION get_stream_integrity_report(
    p_org_id UUID,
    p_stream_id UUID
)
RETURNS TABLE (
    is_valid BOOLEAN,
    event_count INTEGER,
    broken_at_version INTEGER,
    error_message TEXT,
    first_hash TEXT,
    last_hash TEXT
) AS $$
DECLARE
    prev_hash TEXT := '0000000000000000000000000000000000000000000000000000000000000000';
    prev_version INTEGER := 0;
    curr_event RECORD;
    broken_found BOOLEAN := FALSE;
    broken_version INTEGER := NULL;
    error_msg TEXT := NULL;
    total_count INTEGER := 0;
    first_event_hash TEXT := NULL;
    last_event_hash TEXT := NULL;
BEGIN
    FOR curr_event IN
        SELECT * FROM events
        WHERE org_id = p_org_id AND stream_id = p_stream_id
        ORDER BY version ASC
    LOOP
        total_count := total_count + 1;
        
        -- Remember first hash
        IF first_event_hash IS NULL THEN
            first_event_hash := curr_event.hash;
        END IF;
        
        -- Update last hash
        last_event_hash := curr_event.hash;
        
        -- Check version sequence
        IF curr_event.version != prev_version + 1 AND NOT broken_found THEN
            broken_found := TRUE;
            broken_version := curr_event.version;
            error_msg := format('Version gap: expected %s, got %s', 
                prev_version + 1, curr_event.version);
        END IF;
        
        -- Check previous hash chain
        IF curr_event.previous_hash != prev_hash AND NOT broken_found THEN
            broken_found := TRUE;
            broken_version := curr_event.version;
            error_msg := format('Hash chain broken at version %s', curr_event.version);
        END IF;
        
        prev_hash := curr_event.hash;
        prev_version := curr_event.version;
    END LOOP;
    
    RETURN QUERY SELECT
        NOT broken_found AS is_valid,
        total_count AS event_count,
        broken_version AS broken_at_version,
        error_msg AS error_message,
        first_event_hash AS first_hash,
        last_event_hash AS last_hash;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =====================================================
-- View: Stream Summary
-- =====================================================

CREATE OR REPLACE VIEW stream_summary AS
SELECT 
    org_id,
    stream_id,
    stream_type,
    COUNT(*) as event_count,
    MIN(version) as first_version,
    MAX(version) as latest_version,
    MIN(occurred_at) as started_at,
    MAX(occurred_at) as last_activity_at,
    (SELECT hash FROM events e2 
     WHERE e2.org_id = events.org_id 
       AND e2.stream_id = events.stream_id 
     ORDER BY version DESC LIMIT 1) as latest_hash
FROM events
GROUP BY org_id, stream_id, stream_type;

-- Grant select on view
GRANT SELECT ON stream_summary TO authenticated;

-- =====================================================
-- Comments for documentation
-- =====================================================

COMMENT ON FUNCTION validate_event_hash_chain() IS 
'Validates hash chain integrity on every event insert. Ensures:
1. Version is sequential (no gaps)
2. previous_hash links to actual previous event
3. First event has version=1 and genesis hash';

COMMENT ON FUNCTION get_stream_integrity_report(UUID, UUID) IS 
'Returns comprehensive integrity report for a stream.
Use for periodic integrity checks and compliance audits.';

COMMENT ON VIEW stream_summary IS 
'Aggregated view of all event streams with latest version and hash.
Useful for monitoring and dashboard queries.';
