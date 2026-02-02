-- ============================================================
-- Migration 007: SLA Tables
-- ============================================================
-- 
-- This migration creates tables for SLA definitions and instances.
-- While we use event sourcing for state, these tables provide:
-- 1. Fast queries for active SLAs (vs replaying all events)
-- 2. Index support for dashboard queries
-- 3. Materialized view of current state
--
-- Note: These tables are projections of event store data.
-- The event store remains the source of truth.
-- ============================================================

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- SLA DEFINITIONS (Templates)
-- ============================================================
-- Stores SLA templates that can be attached to workflows.
-- Definitions are created once and reused across many workflows.

CREATE TABLE IF NOT EXISTS sla_definitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Definition details
    name VARCHAR(100) NOT NULL,
    description TEXT,
    priority VARCHAR(10) NOT NULL DEFAULT 'p3',  -- p1, p2, p3, p4
    
    -- Time limits (in minutes)
    soft_limit_minutes INTEGER NOT NULL CHECK (soft_limit_minutes > 0),
    hard_limit_minutes INTEGER NOT NULL CHECK (hard_limit_minutes > 0),
    
    -- Business hours configuration (JSON)
    -- {start_hour, end_hour, timezone, business_days, excluded_dates}
    business_hours_only BOOLEAN DEFAULT FALSE,
    business_hours_config JSONB,
    
    -- States where timer pauses (e.g., ["paused", "waiting_customer"])
    excluded_states JSONB DEFAULT '["paused", "blocked"]'::jsonb,
    
    -- Escalation configuration (JSON)
    -- {notify_on_soft, notify_on_hard, escalation_chain, auto_assign}
    escalation_config JSONB,
    
    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    is_archived BOOLEAN DEFAULT FALSE,
    
    -- Audit fields
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID NOT NULL REFERENCES users(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT hard_limit_greater_than_soft 
        CHECK (hard_limit_minutes > soft_limit_minutes),
    CONSTRAINT valid_priority 
        CHECK (priority IN ('p1', 'p2', 'p3', 'p4'))
);

-- Indexes for sla_definitions
CREATE INDEX idx_sla_definitions_org_id ON sla_definitions(org_id);
CREATE INDEX idx_sla_definitions_priority ON sla_definitions(org_id, priority);
CREATE INDEX idx_sla_definitions_active ON sla_definitions(org_id) WHERE NOT is_archived;

-- RLS for sla_definitions
ALTER TABLE sla_definitions ENABLE ROW LEVEL SECURITY;

CREATE POLICY sla_definitions_tenant_isolation ON sla_definitions
    USING (org_id = current_setting('app.current_org_id')::uuid);

-- ============================================================
-- SLA INSTANCES (Active SLAs attached to workflows)
-- ============================================================
-- Tracks the actual SLA instance for each workflow.
-- This is a materialized view of the event-sourced state.

CREATE TABLE IF NOT EXISTS sla_instances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    definition_id UUID NOT NULL REFERENCES sla_definitions(id),
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    
    -- Current status
    -- pending: not started, active: running, soft_breach: over soft limit
    -- hard_breach: over hard limit, met: completed in time, cancelled: cancelled
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    
    -- Timer state
    started_at TIMESTAMPTZ,
    paused_at TIMESTAMPTZ,  -- NULL if not paused
    total_paused_seconds NUMERIC DEFAULT 0,
    
    -- Deadlines (calculated from definition at start time)
    soft_deadline TIMESTAMPTZ,
    hard_deadline TIMESTAMPTZ,
    
    -- Completion
    completed_at TIMESTAMPTZ,
    
    -- Metadata and audit
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Event sourcing reference
    current_version INTEGER DEFAULT 0,  -- Last processed event version
    
    -- Constraints
    CONSTRAINT valid_status CHECK (
        status IN ('pending', 'active', 'soft_breach', 'hard_breach', 'met', 'cancelled')
    ),
    CONSTRAINT paused_implies_started CHECK (
        paused_at IS NULL OR started_at IS NOT NULL
    )
);

-- Indexes for sla_instances
CREATE INDEX idx_sla_instances_org_id ON sla_instances(org_id);
CREATE INDEX idx_sla_instances_workflow ON sla_instances(workflow_id);
CREATE INDEX idx_sla_instances_definition ON sla_instances(definition_id);
CREATE INDEX idx_sla_instances_status ON sla_instances(org_id, status);
CREATE INDEX idx_sla_instances_active ON sla_instances(org_id) 
    WHERE status IN ('pending', 'active');
CREATE INDEX idx_sla_instances_deadline ON sla_instances(hard_deadline) 
    WHERE status IN ('pending', 'active', 'soft_breach');

-- Partial index for breach monitoring
CREATE INDEX idx_sla_instances_at_risk ON sla_instances(org_id, hard_deadline)
    WHERE status = 'active' OR status = 'soft_breach';

-- RLS for sla_instances
ALTER TABLE sla_instances ENABLE ROW LEVEL SECURITY;

CREATE POLICY sla_instances_tenant_isolation ON sla_instances
    USING (org_id = current_setting('app.current_org_id')::uuid);

-- ============================================================
-- SLA BREACH HISTORY (Record of all breaches)
-- ============================================================
-- Immutable record of breach events for audit and reporting.

CREATE TABLE IF NOT EXISTS sla_breach_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    instance_id UUID NOT NULL REFERENCES sla_instances(id),
    workflow_id UUID NOT NULL,
    
    -- Breach details
    breach_type VARCHAR(20) NOT NULL,  -- soft_breach, hard_breach
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exceeded_by_minutes NUMERIC NOT NULL,
    elapsed_minutes NUMERIC NOT NULL,
    
    -- Context at time of breach
    workflow_state VARCHAR(50),
    assigned_to UUID,
    
    -- Resolution tracking
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by UUID,
    resolution_notes TEXT,
    
    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    
    CONSTRAINT valid_breach_type CHECK (
        breach_type IN ('soft_breach', 'hard_breach')
    )
);

-- Indexes for breach history
CREATE INDEX idx_breach_history_org ON sla_breach_history(org_id);
CREATE INDEX idx_breach_history_instance ON sla_breach_history(instance_id);
CREATE INDEX idx_breach_history_workflow ON sla_breach_history(workflow_id);
CREATE INDEX idx_breach_history_time ON sla_breach_history(org_id, detected_at);
CREATE INDEX idx_breach_history_unack ON sla_breach_history(org_id) 
    WHERE acknowledged_at IS NULL;

-- RLS for breach history
ALTER TABLE sla_breach_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY breach_history_tenant_isolation ON sla_breach_history
    USING (org_id = current_setting('app.current_org_id')::uuid);

-- ============================================================
-- FUNCTIONS
-- ============================================================

-- Function to calculate effective elapsed seconds for an SLA instance
CREATE OR REPLACE FUNCTION calculate_sla_elapsed_seconds(instance_id UUID)
RETURNS NUMERIC AS $$
DECLARE
    inst RECORD;
    end_time TIMESTAMPTZ;
    elapsed NUMERIC;
BEGIN
    SELECT * INTO inst FROM sla_instances WHERE id = instance_id;
    
    IF inst IS NULL OR inst.started_at IS NULL THEN
        RETURN 0;
    END IF;
    
    -- Use paused_at if paused, otherwise now()
    IF inst.paused_at IS NOT NULL THEN
        end_time := inst.paused_at;
    ELSIF inst.completed_at IS NOT NULL THEN
        end_time := inst.completed_at;
    ELSE
        end_time := NOW();
    END IF;
    
    -- Calculate elapsed minus paused time
    elapsed := EXTRACT(EPOCH FROM (end_time - inst.started_at)) - inst.total_paused_seconds;
    
    RETURN GREATEST(0, elapsed);
END;
$$ LANGUAGE plpgsql;

-- Function to check if an SLA is breached
CREATE OR REPLACE FUNCTION check_sla_breach(instance_id UUID)
RETURNS TABLE(
    is_soft_breached BOOLEAN,
    is_hard_breached BOOLEAN,
    elapsed_minutes NUMERIC,
    soft_limit_minutes INTEGER,
    hard_limit_minutes INTEGER
) AS $$
DECLARE
    inst RECORD;
    def RECORD;
    elapsed_sec NUMERIC;
    elapsed_min NUMERIC;
BEGIN
    SELECT * INTO inst FROM sla_instances WHERE id = instance_id;
    SELECT * INTO def FROM sla_definitions WHERE id = inst.definition_id;
    
    elapsed_sec := calculate_sla_elapsed_seconds(instance_id);
    elapsed_min := elapsed_sec / 60;
    
    RETURN QUERY SELECT
        elapsed_min >= def.soft_limit_minutes,
        elapsed_min >= def.hard_limit_minutes,
        elapsed_min,
        def.soft_limit_minutes,
        def.hard_limit_minutes;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- VIEWS
-- ============================================================

-- View for SLA dashboard: active and at-risk SLAs
CREATE OR REPLACE VIEW sla_dashboard AS
SELECT 
    i.id,
    i.org_id,
    i.workflow_id,
    i.status,
    i.started_at,
    i.soft_deadline,
    i.hard_deadline,
    d.name as sla_name,
    d.priority,
    d.soft_limit_minutes,
    d.hard_limit_minutes,
    calculate_sla_elapsed_seconds(i.id) / 60 as elapsed_minutes,
    CASE 
        WHEN i.soft_deadline IS NOT NULL 
        THEN EXTRACT(EPOCH FROM (i.soft_deadline - NOW())) / 60
        ELSE NULL
    END as minutes_to_soft,
    CASE 
        WHEN i.hard_deadline IS NOT NULL 
        THEN EXTRACT(EPOCH FROM (i.hard_deadline - NOW())) / 60
        ELSE NULL
    END as minutes_to_hard,
    CASE
        WHEN i.status IN ('soft_breach', 'hard_breach') THEN 'breached'
        WHEN i.hard_deadline < NOW() THEN 'hard_breach'
        WHEN i.soft_deadline < NOW() THEN 'soft_breach'
        WHEN i.hard_deadline < NOW() + INTERVAL '15 minutes' THEN 'critical'
        WHEN i.soft_deadline < NOW() + INTERVAL '15 minutes' THEN 'warning'
        ELSE 'ok'
    END as risk_level
FROM sla_instances i
JOIN sla_definitions d ON i.definition_id = d.id
WHERE i.status IN ('pending', 'active', 'soft_breach');

-- View for compliance reporting
CREATE OR REPLACE VIEW sla_compliance_summary AS
SELECT
    org_id,
    DATE_TRUNC('day', created_at) as day,
    COUNT(*) as total_instances,
    COUNT(*) FILTER (WHERE status = 'met') as met_count,
    COUNT(*) FILTER (WHERE status IN ('soft_breach', 'hard_breach')) as breached_count,
    COUNT(*) FILTER (WHERE status = 'soft_breach') as soft_breach_count,
    COUNT(*) FILTER (WHERE status = 'hard_breach') as hard_breach_count,
    CASE 
        WHEN COUNT(*) FILTER (WHERE status IN ('met', 'soft_breach', 'hard_breach')) > 0
        THEN ROUND(
            100.0 * COUNT(*) FILTER (WHERE status = 'met') / 
            COUNT(*) FILTER (WHERE status IN ('met', 'soft_breach', 'hard_breach')),
            2
        )
        ELSE 100.0
    END as compliance_rate
FROM sla_instances
WHERE status IN ('met', 'soft_breach', 'hard_breach', 'cancelled')
GROUP BY org_id, DATE_TRUNC('day', created_at);

-- ============================================================
-- TRIGGERS
-- ============================================================

-- Trigger to update updated_at on sla_definitions
CREATE TRIGGER update_sla_definitions_timestamp
    BEFORE UPDATE ON sla_definitions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- SEED DATA: Default SLA Templates (inserted per-org on signup)
-- ============================================================
-- Note: These would typically be inserted during org onboarding.
-- This is a reference for the expected templates.

COMMENT ON TABLE sla_definitions IS 
'SLA templates. Default templates for new orgs:
- P1 Critical: 15min soft / 30min hard (24/7)
- P2 High: 1hr soft / 2hr hard (24/7)
- P3 Medium: 4hr soft / 8hr hard (business hours)
- P4 Low: 24hr soft / 48hr hard (business hours)';
