-- =====================================================
-- TrustPlane Database Schema
-- Multi-tenant, Event-sourced SLA Enforcement Platform
-- =====================================================
-- Run this in Supabase SQL Editor
-- =====================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =====================================================
-- CORE TABLES
-- =====================================================

-- Organizations (Tenants)
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    settings JSONB DEFAULT '{}',
    subscription_tier VARCHAR(50) DEFAULT 'free',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index for slug lookups
CREATE INDEX idx_organizations_slug ON organizations(slug);

-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    auth_id UUID UNIQUE, -- Links to Supabase Auth
    email VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) DEFAULT 'member',
    is_active BOOLEAN DEFAULT true,
    last_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(org_id, email)
);

-- Create indexes
CREATE INDEX idx_users_org_id ON users(org_id);
CREATE INDEX idx_users_auth_id ON users(auth_id);
CREATE INDEX idx_users_email ON users(email);

-- =====================================================
-- ROLES & PERMISSIONS (RBAC)
-- =====================================================

-- Roles
CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    is_system BOOLEAN DEFAULT false, -- System roles can't be deleted
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(org_id, name)
);

CREATE INDEX idx_roles_org_id ON roles(org_id);

-- Permissions
CREATE TABLE permissions (
    id VARCHAR(100) PRIMARY KEY, -- e.g., 'workflow:create'
    name VARCHAR(255) NOT NULL,
    description TEXT,
    resource_type VARCHAR(100) NOT NULL,
    action VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Role-Permission mapping
CREATE TABLE role_permissions (
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    permission_id VARCHAR(100) REFERENCES permissions(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    PRIMARY KEY (role_id, permission_id)
);

-- User-Role mapping
CREATE TABLE user_roles (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    assigned_by UUID REFERENCES users(id),
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    
    PRIMARY KEY (user_id, role_id)
);

-- =====================================================
-- POLICIES (ABAC)
-- =====================================================

CREATE TABLE policies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    effect VARCHAR(10) NOT NULL CHECK (effect IN ('allow', 'deny')),
    actions TEXT[] NOT NULL, -- e.g., ARRAY['workflow:create', 'workflow:approve']
    resources TEXT[] NOT NULL, -- e.g., ARRAY['workflow:*']
    conditions JSONB DEFAULT '{}',
    priority INTEGER DEFAULT 100, -- Lower = higher priority
    is_active BOOLEAN DEFAULT true,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_policies_org_id ON policies(org_id);
CREATE INDEX idx_policies_effect ON policies(effect);

-- =====================================================
-- EVENT STORE (Immutable, Hash-chained)
-- =====================================================

CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    stream_id UUID NOT NULL, -- Aggregate ID (e.g., workflow_id)
    stream_type VARCHAR(100) NOT NULL, -- e.g., 'workflow', 'sla'
    event_type VARCHAR(100) NOT NULL, -- e.g., 'workflow.created'
    version INTEGER NOT NULL, -- Version within stream
    
    -- Event data
    data JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',
    
    -- Integrity (hash chaining)
    hash VARCHAR(64) NOT NULL, -- SHA-256 hash
    previous_hash VARCHAR(64) NOT NULL, -- Previous event hash
    
    -- Actor
    actor_id UUID,
    actor_type VARCHAR(50) DEFAULT 'user', -- user, system, agent
    
    -- Timestamps (immutable)
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Idempotency
    idempotency_key VARCHAR(64) UNIQUE,
    
    -- Ensure ordering within stream
    UNIQUE(stream_id, version)
);

-- Critical indexes for event sourcing
CREATE INDEX idx_events_org_id ON events(org_id);
CREATE INDEX idx_events_stream_id ON events(stream_id);
CREATE INDEX idx_events_stream_type ON events(stream_type);
CREATE INDEX idx_events_event_type ON events(event_type);
CREATE INDEX idx_events_occurred_at ON events(occurred_at);
CREATE INDEX idx_events_actor_id ON events(actor_id);

-- Composite index for stream replay
CREATE INDEX idx_events_stream_replay ON events(org_id, stream_id, version);

-- =====================================================
-- WORKFLOWS
-- =====================================================

-- Workflow definitions (templates)
CREATE TABLE workflow_definitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    workflow_type VARCHAR(100) NOT NULL,
    config JSONB DEFAULT '{}',
    states JSONB NOT NULL, -- State machine definition
    is_active BOOLEAN DEFAULT true,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(org_id, name, version)
);

CREATE INDEX idx_workflow_definitions_org_id ON workflow_definitions(org_id);

-- Workflow instances (projections from events)
-- This is a READ MODEL - updated by projecting events
CREATE TABLE workflows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    definition_id UUID REFERENCES workflow_definitions(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    workflow_type VARCHAR(100) NOT NULL,
    current_state VARCHAR(100) NOT NULL DEFAULT 'pending',
    config JSONB DEFAULT '{}',
    
    -- Denormalized for queries
    event_count INTEGER DEFAULT 0,
    last_event_at TIMESTAMPTZ,
    last_event_hash VARCHAR(64),
    
    -- SLA reference
    sla_definition_id UUID,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_workflows_org_id ON workflows(org_id);
CREATE INDEX idx_workflows_state ON workflows(current_state);
CREATE INDEX idx_workflows_type ON workflows(workflow_type);

-- =====================================================
-- SLA ENGINE
-- =====================================================

-- SLA Definitions (templates)
CREATE TABLE sla_definitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- Time limits (in minutes)
    soft_limit_minutes INTEGER NOT NULL,
    hard_limit_minutes INTEGER NOT NULL,
    
    -- Conditions for SLA to apply
    conditions JSONB DEFAULT '{}',
    
    -- Penalty configuration
    penalty_config JSONB DEFAULT '{
        "base_amount": 0,
        "per_minute": 0,
        "soft_breach_multiplier": 1.0,
        "hard_breach_multiplier": 2.0,
        "max_amount": null,
        "currency": "USD"
    }',
    
    -- Notification configuration
    notification_config JSONB DEFAULT '{
        "soft_breach": ["email", "webhook"],
        "hard_breach": ["email", "webhook", "sms"],
        "warning_thresholds": [0.5, 0.75, 0.9]
    }',
    
    is_active BOOLEAN DEFAULT true,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(org_id, name, version),
    CHECK (hard_limit_minutes > soft_limit_minutes)
);

CREATE INDEX idx_sla_definitions_org_id ON sla_definitions(org_id);

-- SLA Instances (active SLAs on workflows)
CREATE TABLE sla_instances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    definition_id UUID NOT NULL REFERENCES sla_definitions(id),
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    
    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'met', 'soft_breach', 'hard_breach')),
    
    -- Timer tracking
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paused_at TIMESTAMPTZ,
    total_paused_seconds NUMERIC DEFAULT 0,
    
    -- Computed deadlines
    soft_deadline TIMESTAMPTZ NOT NULL,
    hard_deadline TIMESTAMPTZ NOT NULL,
    
    -- Breach info
    breached_at TIMESTAMPTZ,
    breach_severity VARCHAR(50),
    
    -- Completion
    completed_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(workflow_id, definition_id)
);

CREATE INDEX idx_sla_instances_org_id ON sla_instances(org_id);
CREATE INDEX idx_sla_instances_workflow_id ON sla_instances(workflow_id);
CREATE INDEX idx_sla_instances_status ON sla_instances(status);
CREATE INDEX idx_sla_instances_soft_deadline ON sla_instances(soft_deadline);
CREATE INDEX idx_sla_instances_hard_deadline ON sla_instances(hard_deadline);

-- SLA Breaches (historical record)
CREATE TABLE sla_breaches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    instance_id UUID NOT NULL REFERENCES sla_instances(id),
    workflow_id UUID NOT NULL REFERENCES workflows(id),
    definition_id UUID NOT NULL REFERENCES sla_definitions(id),
    
    -- Breach details
    severity VARCHAR(50) NOT NULL 
        CHECK (severity IN ('warning', 'soft', 'hard', 'critical')),
    breach_type VARCHAR(50) NOT NULL,
    
    -- Timing
    expected_deadline TIMESTAMPTZ NOT NULL,
    actual_completion TIMESTAMPTZ,
    exceeded_by_minutes NUMERIC NOT NULL,
    
    -- Penalty
    penalty_applied BOOLEAN DEFAULT false,
    penalty_amount NUMERIC,
    penalty_currency VARCHAR(10) DEFAULT 'USD',
    penalty_details JSONB DEFAULT '{}',
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sla_breaches_org_id ON sla_breaches(org_id);
CREATE INDEX idx_sla_breaches_workflow_id ON sla_breaches(workflow_id);
CREATE INDEX idx_sla_breaches_severity ON sla_breaches(severity);
CREATE INDEX idx_sla_breaches_created_at ON sla_breaches(created_at);

-- =====================================================
-- AUDIT LOGS (Immutable)
-- =====================================================

CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Actor
    actor_id UUID NOT NULL,
    actor_type VARCHAR(50) NOT NULL, -- user, system, agent
    actor_email VARCHAR(255),
    
    -- Action
    action VARCHAR(50) NOT NULL, -- create, read, update, delete, approve, etc.
    resource_type VARCHAR(100) NOT NULL, -- workflow, sla, policy, etc.
    resource_id UUID NOT NULL,
    
    -- Details
    reason TEXT,
    changes JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    
    -- Context
    ip_address INET,
    user_agent TEXT,
    
    -- Linked event
    event_id UUID REFERENCES events(id),
    
    -- Timestamp (immutable)
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_org_id ON audit_logs(org_id);
CREATE INDEX idx_audit_logs_actor_id ON audit_logs(actor_id);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_occurred_at ON audit_logs(occurred_at);

-- =====================================================
-- AI AGENT DECISIONS
-- =====================================================

CREATE TABLE agent_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Agent info
    agent_type VARCHAR(50) NOT NULL, -- sla_risk, policy, integrity, decision
    
    -- Context
    workflow_id UUID REFERENCES workflows(id),
    trigger_event_id UUID REFERENCES events(id),
    
    -- Decision
    decision VARCHAR(100) NOT NULL,
    confidence VARCHAR(20) NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    reasoning TEXT NOT NULL,
    recommendations TEXT[],
    
    -- Escalation
    requires_human_review BOOLEAN DEFAULT false,
    human_review_completed BOOLEAN DEFAULT false,
    human_reviewer_id UUID REFERENCES users(id),
    human_decision VARCHAR(100),
    human_notes TEXT,
    
    -- Raw outputs (for debugging)
    raw_analysis JSONB DEFAULT '{}',
    raw_output JSONB DEFAULT '{}',
    
    -- Linked decision event
    decision_event_id UUID REFERENCES events(id),
    
    -- Timing
    analysis_started_at TIMESTAMPTZ,
    analysis_completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_agent_decisions_org_id ON agent_decisions(org_id);
CREATE INDEX idx_agent_decisions_agent_type ON agent_decisions(agent_type);
CREATE INDEX idx_agent_decisions_workflow_id ON agent_decisions(workflow_id);
CREATE INDEX idx_agent_decisions_requires_review ON agent_decisions(requires_human_review);
CREATE INDEX idx_agent_decisions_created_at ON agent_decisions(created_at);

-- =====================================================
-- HELPER FUNCTIONS
-- =====================================================

-- Function to get current user's org_id from JWT
CREATE OR REPLACE FUNCTION auth.org_id()
RETURNS UUID AS $$
BEGIN
    RETURN COALESCE(
        (current_setting('request.jwt.claims', true)::json->>'org_id')::uuid,
        NULL
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get current user's ID from JWT
CREATE OR REPLACE FUNCTION auth.user_id()
RETURNS UUID AS $$
BEGIN
    RETURN COALESCE(
        (current_setting('request.jwt.claims', true)::json->>'sub')::uuid,
        NULL
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get current user's role from JWT
CREATE OR REPLACE FUNCTION auth.user_role()
RETURNS TEXT AS $$
BEGIN
    RETURN COALESCE(
        current_setting('request.jwt.claims', true)::json->>'role',
        'member'
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply updated_at trigger to relevant tables
CREATE TRIGGER update_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_roles_updated_at
    BEFORE UPDATE ON roles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_policies_updated_at
    BEFORE UPDATE ON policies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_workflow_definitions_updated_at
    BEFORE UPDATE ON workflow_definitions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_workflows_updated_at
    BEFORE UPDATE ON workflows
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_sla_definitions_updated_at
    BEFORE UPDATE ON sla_definitions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_sla_instances_updated_at
    BEFORE UPDATE ON sla_instances
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
