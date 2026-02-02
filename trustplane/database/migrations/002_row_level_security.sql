-- =====================================================
-- TrustPlane Row Level Security (RLS) Policies
-- Multi-tenant isolation using JWT claims
-- =====================================================
-- Run this AFTER 001_initial_schema.sql
-- =====================================================

-- =====================================================
-- ENABLE RLS ON ALL TABLES
-- =====================================================

ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflows ENABLE ROW LEVEL SECURITY;
ALTER TABLE sla_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sla_instances ENABLE ROW LEVEL SECURITY;
ALTER TABLE sla_breaches ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_decisions ENABLE ROW LEVEL SECURITY;

-- =====================================================
-- ORGANIZATIONS
-- Users can only see their own organization
-- =====================================================

CREATE POLICY "Users can view their own organization"
    ON organizations FOR SELECT
    USING (id = auth.org_id());

CREATE POLICY "Service role can manage all organizations"
    ON organizations FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- USERS
-- Users can see other users in their org
-- Only admins can create/update users
-- =====================================================

CREATE POLICY "Users can view users in their organization"
    ON users FOR SELECT
    USING (org_id = auth.org_id());

CREATE POLICY "Users can view their own profile"
    ON users FOR SELECT
    USING (auth_id = auth.uid());

CREATE POLICY "Admins can insert users in their organization"
    ON users FOR INSERT
    WITH CHECK (
        org_id = auth.org_id() 
        AND auth.user_role() = 'admin'
    );

CREATE POLICY "Admins can update users in their organization"
    ON users FOR UPDATE
    USING (
        org_id = auth.org_id() 
        AND auth.user_role() = 'admin'
    );

CREATE POLICY "Users can update their own profile"
    ON users FOR UPDATE
    USING (auth_id = auth.uid())
    WITH CHECK (
        auth_id = auth.uid()
        AND org_id = auth.org_id() -- Cannot change org
    );

CREATE POLICY "Service role can manage all users"
    ON users FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- ROLES
-- Org-scoped, admin-managed
-- =====================================================

CREATE POLICY "Users can view roles in their organization"
    ON roles FOR SELECT
    USING (org_id = auth.org_id());

CREATE POLICY "Admins can manage roles in their organization"
    ON roles FOR ALL
    USING (
        org_id = auth.org_id() 
        AND auth.user_role() = 'admin'
    );

CREATE POLICY "Service role can manage all roles"
    ON roles FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- PERMISSIONS (System-wide, read-only for users)
-- =====================================================

CREATE POLICY "All authenticated users can view permissions"
    ON permissions FOR SELECT
    USING (auth.role() IS NOT NULL);

CREATE POLICY "Service role can manage permissions"
    ON permissions FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- ROLE_PERMISSIONS
-- =====================================================

CREATE POLICY "Users can view role permissions for their org roles"
    ON role_permissions FOR SELECT
    USING (
        role_id IN (
            SELECT id FROM roles WHERE org_id = auth.org_id()
        )
    );

CREATE POLICY "Admins can manage role permissions"
    ON role_permissions FOR ALL
    USING (
        role_id IN (
            SELECT id FROM roles WHERE org_id = auth.org_id()
        )
        AND auth.user_role() = 'admin'
    );

CREATE POLICY "Service role can manage all role permissions"
    ON role_permissions FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- USER_ROLES
-- =====================================================

CREATE POLICY "Users can view user roles in their organization"
    ON user_roles FOR SELECT
    USING (
        user_id IN (
            SELECT id FROM users WHERE org_id = auth.org_id()
        )
    );

CREATE POLICY "Admins can manage user roles in their organization"
    ON user_roles FOR ALL
    USING (
        user_id IN (
            SELECT id FROM users WHERE org_id = auth.org_id()
        )
        AND auth.user_role() = 'admin'
    );

CREATE POLICY "Service role can manage all user roles"
    ON user_roles FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- POLICIES (ABAC)
-- =====================================================

CREATE POLICY "Users can view policies in their organization"
    ON policies FOR SELECT
    USING (org_id = auth.org_id());

CREATE POLICY "Admins can manage policies in their organization"
    ON policies FOR ALL
    USING (
        org_id = auth.org_id() 
        AND auth.user_role() = 'admin'
    );

CREATE POLICY "Service role can manage all policies"
    ON policies FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- EVENTS (Immutable - INSERT only, no UPDATE/DELETE)
-- =====================================================

CREATE POLICY "Users can view events in their organization"
    ON events FOR SELECT
    USING (org_id = auth.org_id());

CREATE POLICY "Users can insert events in their organization"
    ON events FOR INSERT
    WITH CHECK (org_id = auth.org_id());

-- NO UPDATE OR DELETE POLICIES - Events are immutable!

CREATE POLICY "Service role can view all events"
    ON events FOR SELECT
    USING (auth.role() = 'service_role');

CREATE POLICY "Service role can insert events"
    ON events FOR INSERT
    WITH CHECK (auth.role() = 'service_role');

-- =====================================================
-- WORKFLOW DEFINITIONS
-- =====================================================

CREATE POLICY "Users can view workflow definitions in their organization"
    ON workflow_definitions FOR SELECT
    USING (org_id = auth.org_id());

CREATE POLICY "Admins can manage workflow definitions"
    ON workflow_definitions FOR ALL
    USING (
        org_id = auth.org_id() 
        AND auth.user_role() = 'admin'
    );

CREATE POLICY "Service role can manage all workflow definitions"
    ON workflow_definitions FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- WORKFLOWS
-- =====================================================

CREATE POLICY "Users can view workflows in their organization"
    ON workflows FOR SELECT
    USING (org_id = auth.org_id());

CREATE POLICY "Users can create workflows in their organization"
    ON workflows FOR INSERT
    WITH CHECK (org_id = auth.org_id());

CREATE POLICY "Users can update workflows in their organization"
    ON workflows FOR UPDATE
    USING (org_id = auth.org_id());

CREATE POLICY "Admins can delete workflows in their organization"
    ON workflows FOR DELETE
    USING (
        org_id = auth.org_id() 
        AND auth.user_role() = 'admin'
    );

CREATE POLICY "Service role can manage all workflows"
    ON workflows FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- SLA DEFINITIONS
-- =====================================================

CREATE POLICY "Users can view SLA definitions in their organization"
    ON sla_definitions FOR SELECT
    USING (org_id = auth.org_id());

CREATE POLICY "Admins can manage SLA definitions"
    ON sla_definitions FOR ALL
    USING (
        org_id = auth.org_id() 
        AND auth.user_role() = 'admin'
    );

CREATE POLICY "Service role can manage all SLA definitions"
    ON sla_definitions FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- SLA INSTANCES
-- =====================================================

CREATE POLICY "Users can view SLA instances in their organization"
    ON sla_instances FOR SELECT
    USING (org_id = auth.org_id());

CREATE POLICY "Users can create SLA instances in their organization"
    ON sla_instances FOR INSERT
    WITH CHECK (org_id = auth.org_id());

CREATE POLICY "System can update SLA instances"
    ON sla_instances FOR UPDATE
    USING (org_id = auth.org_id());

CREATE POLICY "Service role can manage all SLA instances"
    ON sla_instances FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- SLA BREACHES (Immutable records)
-- =====================================================

CREATE POLICY "Users can view SLA breaches in their organization"
    ON sla_breaches FOR SELECT
    USING (org_id = auth.org_id());

CREATE POLICY "System can create SLA breaches"
    ON sla_breaches FOR INSERT
    WITH CHECK (org_id = auth.org_id());

-- NO UPDATE OR DELETE - Breach records are immutable

CREATE POLICY "Service role can manage all SLA breaches"
    ON sla_breaches FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- AUDIT LOGS (Immutable)
-- =====================================================

CREATE POLICY "Users can view audit logs in their organization"
    ON audit_logs FOR SELECT
    USING (org_id = auth.org_id());

CREATE POLICY "System can create audit logs"
    ON audit_logs FOR INSERT
    WITH CHECK (org_id = auth.org_id());

-- NO UPDATE OR DELETE - Audit logs are immutable

CREATE POLICY "Service role can manage all audit logs"
    ON audit_logs FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- AGENT DECISIONS
-- =====================================================

CREATE POLICY "Users can view agent decisions in their organization"
    ON agent_decisions FOR SELECT
    USING (org_id = auth.org_id());

CREATE POLICY "System can create agent decisions"
    ON agent_decisions FOR INSERT
    WITH CHECK (org_id = auth.org_id());

CREATE POLICY "Admins can update agent decisions (human review)"
    ON agent_decisions FOR UPDATE
    USING (
        org_id = auth.org_id()
        AND requires_human_review = true
    );

CREATE POLICY "Service role can manage all agent decisions"
    ON agent_decisions FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- FORCE RLS FOR ALL ROLES (Including table owners)
-- This ensures even admin queries go through RLS
-- =====================================================

ALTER TABLE organizations FORCE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
ALTER TABLE roles FORCE ROW LEVEL SECURITY;
ALTER TABLE permissions FORCE ROW LEVEL SECURITY;
ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY;
ALTER TABLE user_roles FORCE ROW LEVEL SECURITY;
ALTER TABLE policies FORCE ROW LEVEL SECURITY;
ALTER TABLE events FORCE ROW LEVEL SECURITY;
ALTER TABLE workflow_definitions FORCE ROW LEVEL SECURITY;
ALTER TABLE workflows FORCE ROW LEVEL SECURITY;
ALTER TABLE sla_definitions FORCE ROW LEVEL SECURITY;
ALTER TABLE sla_instances FORCE ROW LEVEL SECURITY;
ALTER TABLE sla_breaches FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
ALTER TABLE agent_decisions FORCE ROW LEVEL SECURITY;
