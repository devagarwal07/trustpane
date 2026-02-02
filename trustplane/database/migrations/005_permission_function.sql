"""
Database function for getting user permissions
This should be created in Supabase SQL Editor
"""

# Add this function to your Supabase database:
SQL_FUNCTION = """
-- Function to get all permissions for a user
CREATE OR REPLACE FUNCTION get_user_permissions(p_user_id UUID, p_org_id UUID)
RETURNS TABLE(permission_id VARCHAR) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT rp.permission_id
    FROM user_roles ur
    JOIN roles r ON ur.role_id = r.id
    JOIN role_permissions rp ON r.id = rp.role_id
    JOIN users u ON ur.user_id = u.id
    WHERE u.id = p_user_id
    AND u.org_id = p_org_id
    AND r.org_id = p_org_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
"""
