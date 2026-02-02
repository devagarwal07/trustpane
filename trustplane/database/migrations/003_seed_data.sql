-- =====================================================
-- TrustPlane Seed Data
-- System permissions and default roles
-- =====================================================
-- Run this AFTER 002_row_level_security.sql
-- =====================================================

-- =====================================================
-- SYSTEM PERMISSIONS
-- =====================================================

INSERT INTO permissions (id, name, description, resource_type, action) VALUES
-- Workflow permissions
('workflow:create', 'Create Workflow', 'Create new workflows', 'workflow', 'create'),
('workflow:read', 'Read Workflow', 'View workflow details', 'workflow', 'read'),
('workflow:update', 'Update Workflow', 'Modify workflow data', 'workflow', 'update'),
('workflow:delete', 'Delete Workflow', 'Remove workflows', 'workflow', 'delete'),
('workflow:transition', 'Transition Workflow', 'Change workflow state', 'workflow', 'transition'),
('workflow:approve', 'Approve Workflow', 'Approve workflow actions', 'workflow', 'approve'),
('workflow:reject', 'Reject Workflow', 'Reject workflow actions', 'workflow', 'reject'),

-- SLA permissions
('sla:create', 'Create SLA', 'Create SLA definitions', 'sla', 'create'),
('sla:read', 'Read SLA', 'View SLA details', 'sla', 'read'),
('sla:update', 'Update SLA', 'Modify SLA definitions', 'sla', 'update'),
('sla:delete', 'Delete SLA', 'Remove SLA definitions', 'sla', 'delete'),

-- Policy permissions
('policy:create', 'Create Policy', 'Create access policies', 'policy', 'create'),
('policy:read', 'Read Policy', 'View policy details', 'policy', 'read'),
('policy:update', 'Update Policy', 'Modify policies', 'policy', 'update'),
('policy:delete', 'Delete Policy', 'Remove policies', 'policy', 'delete'),

-- User management permissions
('user:create', 'Create User', 'Add new users', 'user', 'create'),
('user:read', 'Read User', 'View user profiles', 'user', 'read'),
('user:update', 'Update User', 'Modify user data', 'user', 'update'),
('user:delete', 'Delete User', 'Remove users', 'user', 'delete'),
('user:assign_role', 'Assign Role', 'Assign roles to users', 'user', 'assign_role'),

-- Role management permissions
('role:create', 'Create Role', 'Create new roles', 'role', 'create'),
('role:read', 'Read Role', 'View role details', 'role', 'read'),
('role:update', 'Update Role', 'Modify roles', 'role', 'update'),
('role:delete', 'Delete Role', 'Remove roles', 'role', 'delete'),

-- Audit permissions
('audit:read', 'Read Audit Logs', 'View audit logs', 'audit', 'read'),
('audit:export', 'Export Audit Logs', 'Export audit data', 'audit', 'export'),

-- Agent permissions
('agent:read', 'Read Agent Decisions', 'View AI agent decisions', 'agent', 'read'),
('agent:review', 'Review Agent Decisions', 'Review and override AI decisions', 'agent', 'review'),
('agent:trigger', 'Trigger Agent', 'Manually trigger agent evaluation', 'agent', 'trigger'),

-- Event permissions
('event:read', 'Read Events', 'View event stream', 'event', 'read'),
('event:verify', 'Verify Events', 'Verify event integrity', 'event', 'verify'),

-- Organization permissions
('org:read', 'Read Organization', 'View organization details', 'organization', 'read'),
('org:update', 'Update Organization', 'Modify organization settings', 'organization', 'update')

ON CONFLICT (id) DO NOTHING;

-- =====================================================
-- NOTE: Default roles should be created per-organization
-- when the organization is created. Here's an example
-- of what that looks like:
-- =====================================================

-- Example: Creating default roles for a new organization
-- This would be called by the application when creating an org

/*
-- Admin role (full access)
INSERT INTO roles (org_id, name, description, is_system)
VALUES ('org-uuid-here', 'admin', 'Full administrative access', true);

-- Manager role (approval rights)
INSERT INTO roles (org_id, name, description, is_system)
VALUES ('org-uuid-here', 'manager', 'Workflow management and approval', true);

-- Member role (basic access)
INSERT INTO roles (org_id, name, description, is_system)
VALUES ('org-uuid-here', 'member', 'Basic workflow access', true);

-- Viewer role (read-only)
INSERT INTO roles (org_id, name, description, is_system)
VALUES ('org-uuid-here', 'viewer', 'Read-only access', true);
*/

-- =====================================================
-- FUNCTION: Create default roles for new organization
-- =====================================================

CREATE OR REPLACE FUNCTION create_default_roles_for_org(org_uuid UUID)
RETURNS VOID AS $$
DECLARE
    admin_role_id UUID;
    manager_role_id UUID;
    member_role_id UUID;
    viewer_role_id UUID;
BEGIN
    -- Create Admin role
    INSERT INTO roles (org_id, name, description, is_system)
    VALUES (org_uuid, 'admin', 'Full administrative access', true)
    RETURNING id INTO admin_role_id;
    
    -- Assign all permissions to admin
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT admin_role_id, id FROM permissions;
    
    -- Create Manager role
    INSERT INTO roles (org_id, name, description, is_system)
    VALUES (org_uuid, 'manager', 'Workflow management and approval', true)
    RETURNING id INTO manager_role_id;
    
    -- Assign manager permissions
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT manager_role_id, id FROM permissions
    WHERE id IN (
        'workflow:create', 'workflow:read', 'workflow:update', 'workflow:transition',
        'workflow:approve', 'workflow:reject',
        'sla:read',
        'policy:read',
        'user:read',
        'audit:read',
        'agent:read', 'agent:review',
        'event:read'
    );
    
    -- Create Member role
    INSERT INTO roles (org_id, name, description, is_system)
    VALUES (org_uuid, 'member', 'Basic workflow access', true)
    RETURNING id INTO member_role_id;
    
    -- Assign member permissions
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT member_role_id, id FROM permissions
    WHERE id IN (
        'workflow:create', 'workflow:read', 'workflow:transition',
        'sla:read',
        'user:read',
        'event:read'
    );
    
    -- Create Viewer role
    INSERT INTO roles (org_id, name, description, is_system)
    VALUES (org_uuid, 'viewer', 'Read-only access', true)
    RETURNING id INTO viewer_role_id;
    
    -- Assign viewer permissions
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT viewer_role_id, id FROM permissions
    WHERE id IN (
        'workflow:read',
        'sla:read',
        'user:read',
        'event:read'
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =====================================================
-- TRIGGER: Auto-create default roles when org is created
-- =====================================================

CREATE OR REPLACE FUNCTION on_organization_created()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM create_default_roles_for_org(NEW.id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER trigger_create_default_roles
    AFTER INSERT ON organizations
    FOR EACH ROW
    EXECUTE FUNCTION on_organization_created();
