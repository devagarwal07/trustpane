-- =============================================================
-- Migration: 007_policies_and_roles
-- TrustPlane Policy Engine Tables
-- =============================================================
-- This migration creates the tables for the Rego-compatible
-- policy engine supporting RBAC, ABAC, and domain-specific policies.
-- =============================================================

-- Policies table
CREATE TABLE IF NOT EXISTS policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Policy metadata
    name VARCHAR(100) NOT NULL,
    description TEXT,
    
    -- Policy definition
    effect VARCHAR(10) NOT NULL CHECK (effect IN ('allow', 'deny')),
    type VARCHAR(20) DEFAULT 'abac' CHECK (type IN ('rbac', 'abac', 'workflow', 'sla', 'agent', 'audit')),
    role VARCHAR(50),  -- For RBAC policies
    
    -- Policy rules (JSON arrays)
    actions TEXT[] NOT NULL DEFAULT ARRAY['*'],
    resources TEXT[] NOT NULL DEFAULT ARRAY['*'],
    conditions JSONB DEFAULT '{}',
    
    -- Priority (lower = higher priority)
    priority INTEGER NOT NULL DEFAULT 100 CHECK (priority >= 1 AND priority <= 1000),
    
    -- Status
    is_active BOOLEAN NOT NULL DEFAULT true,
    is_system BOOLEAN NOT NULL DEFAULT false,  -- System policies cannot be deleted
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    UNIQUE(org_id, name, is_active) WHERE is_active = true
);

-- Indexes for policies
CREATE INDEX IF NOT EXISTS idx_policies_org_id ON policies(org_id);
CREATE INDEX IF NOT EXISTS idx_policies_org_active ON policies(org_id, is_active);
CREATE INDEX IF NOT EXISTS idx_policies_type ON policies(type);
CREATE INDEX IF NOT EXISTS idx_policies_effect ON policies(effect);
CREATE INDEX IF NOT EXISTS idx_policies_priority ON policies(priority);
CREATE INDEX IF NOT EXISTS idx_policies_role ON policies(role) WHERE role IS NOT NULL;

-- Roles table
CREATE TABLE IF NOT EXISTS roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Role metadata
    name VARCHAR(50) NOT NULL,
    description TEXT,
    
    -- Permissions (action patterns)
    permissions TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    
    -- Parent role for inheritance
    parent_role_id UUID REFERENCES roles(id),
    
    -- Status
    is_active BOOLEAN NOT NULL DEFAULT true,
    is_system BOOLEAN NOT NULL DEFAULT false,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    UNIQUE(org_id, name) WHERE is_active = true
);

-- Indexes for roles
CREATE INDEX IF NOT EXISTS idx_roles_org_id ON roles(org_id);
CREATE INDEX IF NOT EXISTS idx_roles_org_active ON roles(org_id, is_active);
CREATE INDEX IF NOT EXISTS idx_roles_parent ON roles(parent_role_id);

-- User role assignments table
CREATE TABLE IF NOT EXISTS user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Assignment metadata
    assigned_by UUID REFERENCES users(id),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,  -- Optional expiration
    
    -- Status
    is_active BOOLEAN NOT NULL DEFAULT true,
    
    -- Constraints
    UNIQUE(user_id, role_id) WHERE is_active = true
);

-- Indexes for user_roles
CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_role_id ON user_roles(role_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_org_id ON user_roles(org_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_expires ON user_roles(expires_at) WHERE expires_at IS NOT NULL;

-- Policy evaluation audit log
CREATE TABLE IF NOT EXISTS policy_evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Request context
    user_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    resource VARCHAR(255) NOT NULL,
    
    -- Evaluation result
    decision VARCHAR(20) NOT NULL CHECK (decision IN ('allow', 'deny', 'not_applicable')),
    allowed BOOLEAN NOT NULL,
    
    -- Matched policies
    matched_policy_ids UUID[],
    matched_policy_names TEXT[],
    reasons TEXT[],
    
    -- Performance
    evaluation_time_ms FLOAT,
    input_hash VARCHAR(64),  -- SHA-256 of input for deduplication
    
    -- Timestamps
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Context (stored as JSONB for flexibility)
    context JSONB DEFAULT '{}'
);

-- Indexes for policy_evaluations
CREATE INDEX IF NOT EXISTS idx_policy_eval_org_id ON policy_evaluations(org_id);
CREATE INDEX IF NOT EXISTS idx_policy_eval_user_id ON policy_evaluations(user_id);
CREATE INDEX IF NOT EXISTS idx_policy_eval_action ON policy_evaluations(action);
CREATE INDEX IF NOT EXISTS idx_policy_eval_decision ON policy_evaluations(decision);
CREATE INDEX IF NOT EXISTS idx_policy_eval_time ON policy_evaluations(evaluated_at);
CREATE INDEX IF NOT EXISTS idx_policy_eval_input_hash ON policy_evaluations(input_hash);

-- Partitioning for policy_evaluations (for high-volume)
-- Note: This creates a parent table, partitions should be created separately
-- CREATE TABLE policy_evaluations_y2024m01 PARTITION OF policy_evaluations
--     FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

-- =============================================================
-- Row Level Security (RLS)
-- =============================================================

ALTER TABLE policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy_evaluations ENABLE ROW LEVEL SECURITY;

-- Policies RLS
CREATE POLICY policies_tenant_isolation ON policies
    USING (org_id = current_setting('app.current_org_id')::UUID);

CREATE POLICY policies_select ON policies
    FOR SELECT USING (org_id = current_setting('app.current_org_id')::UUID);

CREATE POLICY policies_insert ON policies
    FOR INSERT WITH CHECK (org_id = current_setting('app.current_org_id')::UUID);

CREATE POLICY policies_update ON policies
    FOR UPDATE USING (org_id = current_setting('app.current_org_id')::UUID);

CREATE POLICY policies_delete ON policies
    FOR DELETE USING (
        org_id = current_setting('app.current_org_id')::UUID
        AND is_system = false
    );

-- Roles RLS
CREATE POLICY roles_tenant_isolation ON roles
    USING (org_id = current_setting('app.current_org_id')::UUID);

-- User Roles RLS
CREATE POLICY user_roles_tenant_isolation ON user_roles
    USING (org_id = current_setting('app.current_org_id')::UUID);

-- Policy Evaluations RLS
CREATE POLICY policy_eval_tenant_isolation ON policy_evaluations
    USING (org_id = current_setting('app.current_org_id')::UUID);

-- =============================================================
-- Helper Functions
-- =============================================================

-- Function to get effective roles for a user (including inherited)
CREATE OR REPLACE FUNCTION get_effective_roles(p_user_id UUID)
RETURNS TABLE(role_id UUID, role_name VARCHAR(50), inherited BOOLEAN) AS $$
WITH RECURSIVE role_tree AS (
    -- Direct role assignments
    SELECT r.id, r.name, r.parent_role_id, false AS inherited
    FROM roles r
    JOIN user_roles ur ON ur.role_id = r.id
    WHERE ur.user_id = p_user_id
      AND ur.is_active = true
      AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
      AND r.is_active = true
    
    UNION
    
    -- Inherited roles
    SELECT r.id, r.name, r.parent_role_id, true AS inherited
    FROM roles r
    JOIN role_tree rt ON r.id = rt.parent_role_id
    WHERE r.is_active = true
)
SELECT id AS role_id, name AS role_name, inherited
FROM role_tree;
$$ LANGUAGE sql STABLE;

-- Function to check if user has permission
CREATE OR REPLACE FUNCTION user_has_permission(
    p_user_id UUID,
    p_action VARCHAR(100)
) RETURNS BOOLEAN AS $$
DECLARE
    v_has_permission BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM get_effective_roles(p_user_id) er
        JOIN roles r ON r.id = er.role_id
        WHERE p_action = ANY(r.permissions)
           OR EXISTS (
               SELECT 1 FROM unnest(r.permissions) AS perm
               WHERE p_action LIKE REPLACE(perm, '*', '%')
           )
    ) INTO v_has_permission;
    
    RETURN v_has_permission;
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to seed default system roles
CREATE OR REPLACE FUNCTION seed_default_roles(p_org_id UUID) RETURNS VOID AS $$
BEGIN
    -- Admin role
    INSERT INTO roles (org_id, name, description, permissions, is_system)
    VALUES (
        p_org_id,
        'admin',
        'Full system administrator',
        ARRAY['*'],
        true
    ) ON CONFLICT DO NOTHING;
    
    -- Manager role
    INSERT INTO roles (org_id, name, description, permissions, is_system)
    VALUES (
        p_org_id,
        'manager',
        'Team manager with elevated permissions',
        ARRAY['workflow:*', 'sla:read', 'sla:create', 'user:read', 'audit:read'],
        true
    ) ON CONFLICT DO NOTHING;
    
    -- User role
    INSERT INTO roles (org_id, name, description, permissions, is_system)
    VALUES (
        p_org_id,
        'user',
        'Standard user',
        ARRAY['workflow:create', 'workflow:read', 'workflow:update', 'workflow:transition', 'sla:read'],
        true
    ) ON CONFLICT DO NOTHING;
    
    -- Viewer role
    INSERT INTO roles (org_id, name, description, permissions, is_system)
    VALUES (
        p_org_id,
        'viewer',
        'Read-only access',
        ARRAY['workflow:read', 'sla:read', 'audit:read'],
        true
    ) ON CONFLICT DO NOTHING;
END;
$$ LANGUAGE plpgsql;

-- =============================================================
-- Triggers
-- =============================================================

-- Update timestamp trigger for policies
CREATE TRIGGER policies_updated_at
    BEFORE UPDATE ON policies
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Update timestamp trigger for roles
CREATE TRIGGER roles_updated_at
    BEFORE UPDATE ON roles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================
-- Comments
-- =============================================================

COMMENT ON TABLE policies IS 'Policy definitions for RBAC/ABAC access control';
COMMENT ON TABLE roles IS 'Role definitions for RBAC';
COMMENT ON TABLE user_roles IS 'User to role assignments';
COMMENT ON TABLE policy_evaluations IS 'Audit log for policy evaluation decisions';

COMMENT ON COLUMN policies.effect IS 'Policy effect: allow or deny';
COMMENT ON COLUMN policies.type IS 'Policy type: rbac, abac, workflow, sla, agent, audit';
COMMENT ON COLUMN policies.priority IS 'Lower priority = higher precedence (1-1000)';
COMMENT ON COLUMN policies.conditions IS 'JSONB conditions for ABAC evaluation';
COMMENT ON COLUMN policies.is_system IS 'System policies cannot be modified or deleted';

COMMENT ON COLUMN roles.permissions IS 'Array of action patterns (supports wildcards)';
COMMENT ON COLUMN roles.parent_role_id IS 'Parent role for inheritance';

COMMENT ON COLUMN policy_evaluations.input_hash IS 'SHA-256 hash of evaluation input for deduplication';
