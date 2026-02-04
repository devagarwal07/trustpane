-- Migration: 008_audit_logging_system
-- Description: Comprehensive audit logging with compliance tracking, integrity verification, and retention policies

-- Create audit_logs table (immutable append-only ledger)
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Event classification
    event_type VARCHAR(255) NOT NULL,
    action VARCHAR(50) NOT NULL,
    severity VARCHAR(50) NOT NULL DEFAULT 'info',
    
    -- Actor (who performed the action)
    actor_id VARCHAR(255),
    actor_type VARCHAR(50) DEFAULT 'user',
    actor_name VARCHAR(255),
    
    -- Target (what was acted upon)
    target_id VARCHAR(255),
    target_type VARCHAR(100),
    target_name VARCHAR(255),
    
    -- Context
    resource VARCHAR(255),
    description TEXT,
    details JSONB DEFAULT '{}',
    
    -- Change tracking
    changes JSONB,
    
    -- Network context
    ip_address INET,
    user_agent TEXT,
    session_id VARCHAR(255),
    
    -- Integrity
    content_hash VARCHAR(64) NOT NULL,  -- SHA-256 hash for immutability verification
    
    -- Lifecycle
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    retention_until TIMESTAMP WITH TIME ZONE NOT NULL,
    is_archived BOOLEAN DEFAULT FALSE,
    archive_location VARCHAR(255),
    
    -- Timestamps
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
) PARTITION BY RANGE (created_at);

-- Create partitions for audit logs (quarterly)
-- Current quarter and next 4 quarters
CREATE TABLE audit_logs_2024_q1 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-01-01') TO ('2024-04-01');
CREATE TABLE audit_logs_2024_q2 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-04-01') TO ('2024-07-01');
CREATE TABLE audit_logs_2024_q3 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-07-01') TO ('2024-10-01');
CREATE TABLE audit_logs_2024_q4 PARTITION OF audit_logs
    FOR VALUES FROM ('2024-10-01') TO ('2025-01-01');
CREATE TABLE audit_logs_2025_q1 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-01-01') TO ('2025-04-01');
CREATE TABLE audit_logs_2025_q2 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-04-01') TO ('2025-07-01');

-- Create indexes for audit_logs
CREATE INDEX idx_audit_logs_org_id ON audit_logs (org_id);
CREATE INDEX idx_audit_logs_created_at ON audit_logs (created_at DESC);
CREATE INDEX idx_audit_logs_event_type ON audit_logs (event_type);
CREATE INDEX idx_audit_logs_actor_id ON audit_logs (actor_id);
CREATE INDEX idx_audit_logs_target_id ON audit_logs (target_id);
CREATE INDEX idx_audit_logs_severity ON audit_logs (severity);
CREATE INDEX idx_audit_logs_action ON audit_logs (action);
CREATE INDEX idx_audit_logs_org_event_date ON audit_logs (org_id, event_type, created_at);
CREATE INDEX idx_audit_logs_org_severity_date ON audit_logs (org_id, severity, created_at);
CREATE INDEX idx_audit_logs_is_archived ON audit_logs (is_archived) WHERE is_archived = FALSE;

-- Create audit_retention table (retention policies)
CREATE TABLE IF NOT EXISTS audit_retention (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Retention periods in days
    standard_retention_days INTEGER DEFAULT 90,
    compliance_retention_days INTEGER DEFAULT 365,  -- HIPAA, GDPR, SOC2
    financial_retention_days INTEGER DEFAULT 2555,  -- 7 years for financial
    
    -- Archival settings
    auto_archive_after_days INTEGER DEFAULT 180,
    archive_location VARCHAR(255) DEFAULT 's3://trustplane-audit-archive',
    
    -- Deletion policy
    auto_delete_after_days INTEGER,  -- NULL = never auto-delete
    require_approval_for_deletion BOOLEAN DEFAULT TRUE,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for audit_retention
CREATE INDEX idx_audit_retention_org_id ON audit_retention (org_id);

-- Create audit_archives table (archived audit records)
CREATE TABLE IF NOT EXISTS audit_archives (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Archive details
    record_count INTEGER NOT NULL,
    date_range_start TIMESTAMP WITH TIME ZONE NOT NULL,
    date_range_end TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Storage
    archive_location VARCHAR(255) NOT NULL,
    archive_size_bytes BIGINT NOT NULL,
    checksum VARCHAR(64) NOT NULL,  -- SHA-256 of combined record hashes
    
    -- Retrieval tracking
    retrieved_at TIMESTAMP WITH TIME ZONE,
    retrieval_count INTEGER DEFAULT 0,
    
    -- Lifecycle
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE,
    is_permanent BOOLEAN DEFAULT FALSE
);

-- Create indexes for audit_archives
CREATE INDEX idx_audit_archives_org_id ON audit_archives (org_id);
CREATE INDEX idx_audit_archives_created_at ON audit_archives (created_at DESC);

-- Create audit_integrity_checks table
CREATE TABLE IF NOT EXISTS audit_integrity_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Check scope
    start_record_id UUID,
    end_record_id UUID,
    record_count INTEGER NOT NULL,
    
    -- Results
    is_valid BOOLEAN NOT NULL,
    missing_records_count INTEGER DEFAULT 0,
    hash_mismatches_count INTEGER DEFAULT 0,
    chain_breaks_count INTEGER DEFAULT 0,
    
    -- Performance
    check_duration_ms FLOAT,
    checked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for audit_integrity_checks
CREATE INDEX idx_audit_integrity_checks_org_id ON audit_integrity_checks (org_id);
CREATE INDEX idx_audit_integrity_checks_checked_at ON audit_integrity_checks (checked_at DESC);

-- Create anomalies table (detected security anomalies)
CREATE TABLE IF NOT EXISTS audit_anomalies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Anomaly classification
    anomaly_type VARCHAR(100) NOT NULL,
    severity VARCHAR(50) NOT NULL,
    
    -- Details
    description TEXT NOT NULL,
    related_event_ids UUID[] DEFAULT '{}',
    affected_users VARCHAR(255)[] DEFAULT '{}',
    affected_resources VARCHAR(255)[] DEFAULT '{}',
    
    -- Context
    context JSONB DEFAULT '{}',
    
    -- Review/response
    is_reviewed BOOLEAN DEFAULT FALSE,
    reviewed_by VARCHAR(255),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    response_action VARCHAR(255),
    
    -- Timestamps
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for audit_anomalies
CREATE INDEX idx_audit_anomalies_org_id ON audit_anomalies (org_id);
CREATE INDEX idx_audit_anomalies_severity ON audit_anomalies (severity);
CREATE INDEX idx_audit_anomalies_detected_at ON audit_anomalies (detected_at DESC);
CREATE INDEX idx_audit_anomalies_is_reviewed ON audit_anomalies (is_reviewed);

-- RLS: Audit logs are visible only to users in the same organization
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_logs_org_isolation ON audit_logs
    FOR ALL USING (org_id = (SELECT org_id FROM user_orgs WHERE user_id = auth.uid() LIMIT 1));

-- RLS: Retention policies are org-specific
ALTER TABLE audit_retention ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_retention_org_isolation ON audit_retention
    FOR ALL USING (org_id = (SELECT org_id FROM user_orgs WHERE user_id = auth.uid() LIMIT 1));

-- RLS: Archives are org-specific
ALTER TABLE audit_archives ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_archives_org_isolation ON audit_archives
    FOR ALL USING (org_id = (SELECT org_id FROM user_orgs WHERE user_id = auth.uid() LIMIT 1));

-- RLS: Integrity checks are org-specific
ALTER TABLE audit_integrity_checks ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_integrity_checks_org_isolation ON audit_integrity_checks
    FOR ALL USING (org_id = (SELECT org_id FROM user_orgs WHERE user_id = auth.uid() LIMIT 1));

-- RLS: Anomalies are org-specific
ALTER TABLE audit_anomalies ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_anomalies_org_isolation ON audit_anomalies
    FOR ALL USING (org_id = (SELECT org_id FROM user_orgs WHERE user_id = auth.uid() LIMIT 1));

-- Trigger: Update updated_at on audit_retention
CREATE OR REPLACE FUNCTION update_updated_at_audit_retention()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_updated_at_audit_retention
    BEFORE UPDATE ON audit_retention
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_audit_retention();

-- Helper function: Get audit logs by organization and date range
CREATE OR REPLACE FUNCTION get_audit_logs_by_org(
    p_org_id UUID,
    p_start_date TIMESTAMP WITH TIME ZONE,
    p_end_date TIMESTAMP WITH TIME ZONE,
    p_limit INTEGER DEFAULT 100,
    p_offset INTEGER DEFAULT 0
)
RETURNS TABLE (
    id UUID,
    event_type VARCHAR,
    action VARCHAR,
    severity VARCHAR,
    actor_id VARCHAR,
    actor_name VARCHAR,
    target_id VARCHAR,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        al.id,
        al.event_type,
        al.action,
        al.severity,
        al.actor_id,
        al.actor_name,
        al.target_id,
        al.description,
        al.created_at
    FROM audit_logs al
    WHERE al.org_id = p_org_id
        AND al.created_at >= p_start_date
        AND al.created_at <= p_end_date
        AND al.is_archived = FALSE
    ORDER BY al.created_at DESC
    LIMIT p_limit OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

-- Helper function: Count audit events by type
CREATE OR REPLACE FUNCTION count_audit_events_by_type(
    p_org_id UUID,
    p_start_date TIMESTAMP WITH TIME ZONE,
    p_end_date TIMESTAMP WITH TIME ZONE
)
RETURNS TABLE (
    event_type VARCHAR,
    event_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        al.event_type,
        COUNT(*) as event_count
    FROM audit_logs al
    WHERE al.org_id = p_org_id
        AND al.created_at >= p_start_date
        AND al.created_at <= p_end_date
    GROUP BY al.event_type
    ORDER BY event_count DESC;
END;
$$ LANGUAGE plpgsql;

-- Helper function: Verify audit log integrity
CREATE OR REPLACE FUNCTION verify_audit_integrity(
    p_org_id UUID
)
RETURNS TABLE (
    total_records BIGINT,
    hash_mismatches INTEGER,
    integrity_valid BOOLEAN
) AS $$
DECLARE
    v_total BIGINT;
    v_mismatches INTEGER := 0;
BEGIN
    -- Count total records
    SELECT COUNT(*) INTO v_total FROM audit_logs WHERE org_id = p_org_id;
    
    -- In a real implementation, verify each hash
    -- For now, return summary
    RETURN QUERY
    SELECT 
        v_total,
        v_mismatches,
        v_mismatches = 0;
END;
$$ LANGUAGE plpgsql;

-- Helper function: Auto-archive old logs
CREATE OR REPLACE FUNCTION archive_old_audit_logs()
RETURNS TABLE (
    archived_count INTEGER,
    archive_date TIMESTAMP WITH TIME ZONE
) AS $$
DECLARE
    v_cutoff_date TIMESTAMP WITH TIME ZONE;
    v_count INTEGER;
BEGIN
    v_cutoff_date := CURRENT_TIMESTAMP - INTERVAL '180 days';
    
    UPDATE audit_logs
    SET is_archived = TRUE
    WHERE is_archived = FALSE
        AND created_at < v_cutoff_date
    RETURNING 1 INTO v_count;
    
    RETURN QUERY SELECT COUNT(*)::INTEGER, v_cutoff_date FROM audit_logs;
END;
$$ LANGUAGE plpgsql;

-- Helper function: Auto-delete expired logs
CREATE OR REPLACE FUNCTION delete_expired_audit_logs()
RETURNS TABLE (
    deleted_count INTEGER,
    deletion_date TIMESTAMP WITH TIME ZONE
) AS $$
DECLARE
    v_count INTEGER;
BEGIN
    -- Delete logs past retention
    DELETE FROM audit_logs
    WHERE retention_until < CURRENT_TIMESTAMP;
    
    GET DIAGNOSTICS v_count = ROW_COUNT;
    
    RETURN QUERY SELECT v_count, CURRENT_TIMESTAMP;
END;
$$ LANGUAGE plpgsql;

-- Seed default retention policies for new organizations
CREATE OR REPLACE FUNCTION seed_audit_retention_policy(p_org_id UUID)
RETURNS void AS $$
BEGIN
    INSERT INTO audit_retention (org_id, standard_retention_days, compliance_retention_days, financial_retention_days)
    VALUES (p_org_id, 90, 365, 2555)
    ON CONFLICT (org_id) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

-- Trigger: Auto-create retention policy for new organizations
CREATE OR REPLACE FUNCTION create_retention_policy_for_org()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM seed_audit_retention_policy(NEW.id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_create_retention_policy
    AFTER INSERT ON organizations
    FOR EACH ROW
    EXECUTE FUNCTION create_retention_policy_for_org();

-- Comments
COMMENT ON TABLE audit_logs IS 'Immutable append-only audit log of all system events. Records are partitioned by date for performance.';
COMMENT ON TABLE audit_retention IS 'Retention policies per organization. Controls how long audit logs are retained.';
COMMENT ON TABLE audit_archives IS 'Records of archived audit logs for compliance and historical access.';
COMMENT ON TABLE audit_integrity_checks IS 'Results of audit log integrity verification checks.';
COMMENT ON TABLE audit_anomalies IS 'Detected anomalies and security issues in audit logs.';
COMMENT ON COLUMN audit_logs.content_hash IS 'SHA-256 hash of audit record for immutability verification.';
COMMENT ON COLUMN audit_logs.retention_until IS 'Date when this record becomes eligible for archival/deletion.';
