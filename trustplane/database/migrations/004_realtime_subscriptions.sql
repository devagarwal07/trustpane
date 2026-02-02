-- =====================================================
-- TrustPlane Realtime Subscriptions
-- Enable Supabase Realtime for live updates
-- =====================================================
-- Run this AFTER 003_seed_data.sql
-- =====================================================

-- Enable realtime for tables that need live updates
-- Note: Be selective - only enable for tables that need it

-- Workflows - for dashboard updates
ALTER PUBLICATION supabase_realtime ADD TABLE workflows;

-- SLA Instances - for SLA monitoring
ALTER PUBLICATION supabase_realtime ADD TABLE sla_instances;

-- SLA Breaches - for breach alerts
ALTER PUBLICATION supabase_realtime ADD TABLE sla_breaches;

-- Agent Decisions - for AI decision notifications
ALTER PUBLICATION supabase_realtime ADD TABLE agent_decisions;

-- Events - for event stream (optional, can be high volume)
-- ALTER PUBLICATION supabase_realtime ADD TABLE events;

-- =====================================================
-- NOTIFICATION FUNCTIONS
-- For custom event triggers
-- =====================================================

-- Function to notify on SLA breach
CREATE OR REPLACE FUNCTION notify_sla_breach()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(
        'sla_breach',
        json_build_object(
            'id', NEW.id,
            'org_id', NEW.org_id,
            'workflow_id', NEW.workflow_id,
            'severity', NEW.severity,
            'exceeded_by_minutes', NEW.exceeded_by_minutes
        )::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_notify_sla_breach
    AFTER INSERT ON sla_breaches
    FOR EACH ROW
    EXECUTE FUNCTION notify_sla_breach();

-- Function to notify on agent decision requiring review
CREATE OR REPLACE FUNCTION notify_agent_decision_review()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.requires_human_review = true THEN
        PERFORM pg_notify(
            'agent_review_needed',
            json_build_object(
                'id', NEW.id,
                'org_id', NEW.org_id,
                'agent_type', NEW.agent_type,
                'workflow_id', NEW.workflow_id,
                'decision', NEW.decision,
                'confidence', NEW.confidence
            )::text
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_notify_agent_review
    AFTER INSERT ON agent_decisions
    FOR EACH ROW
    EXECUTE FUNCTION notify_agent_decision_review();

-- Function to notify on workflow state change
CREATE OR REPLACE FUNCTION notify_workflow_state_change()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.current_state IS DISTINCT FROM NEW.current_state THEN
        PERFORM pg_notify(
            'workflow_state_changed',
            json_build_object(
                'id', NEW.id,
                'org_id', NEW.org_id,
                'workflow_type', NEW.workflow_type,
                'old_state', OLD.current_state,
                'new_state', NEW.current_state
            )::text
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_notify_workflow_state
    AFTER UPDATE ON workflows
    FOR EACH ROW
    EXECUTE FUNCTION notify_workflow_state_change();
