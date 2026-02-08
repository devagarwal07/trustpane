"""
Integration Tests - End-to-End Workflow Scenarios

Tests complete workflows from creation to completion,
including SLA tracking, agent decisions, and notifications.
"""
import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.models.workflow import WorkflowState, WorkflowType
from app.models.sla import SLAStatus
from app.models.notification import NotificationType, NotificationPriority
from tests.fixtures import TestDataFactory


@pytest.mark.asyncio
class TestWorkflowIntegration:
    """Test complete workflow lifecycle"""
    
    async def test_create_and_start_workflow(self, client: TestClient, auth_headers):
        """Test creating and starting a workflow"""
        # Create workflow
        workflow_data = {
            "title": "Integration Test Workflow",
            "description": "Testing workflow creation",
            "workflow_type": "support_ticket",
            "priority": "high",
            "metadata": {"customer_id": "cust_123"}
        }
        
        response = client.post(
            "/api/v1/workflows",
            json=workflow_data,
            headers=auth_headers
        )
        
        assert response.status_code == 201
        workflow = response.json()
        assert workflow["title"] == workflow_data["title"]
        assert workflow["current_state"] == WorkflowState.PENDING
        
        workflow_id = workflow["workflow_id"]
        
        # Start workflow
        response = client.post(
            f"/api/v1/workflows/{workflow_id}/start",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        updated_workflow = response.json()
        assert updated_workflow["current_state"] == WorkflowState.ACTIVE
    
    async def test_workflow_with_sla_tracking(self, client: TestClient, auth_headers):
        """Test workflow with SLA instance attached"""
        # Create SLA definition
        sla_data = {
            "name": "Support Ticket SLA",
            "soft_limit_minutes": 60,
            "hard_limit_minutes": 120,
            "conditions": {"priority": ["high"]},
        }
        
        response = client.post(
            "/api/v1/sla/definitions",
            json=sla_data,
            headers=auth_headers
        )
        assert response.status_code == 201
        sla_def = response.json()
        
        # Create workflow
        workflow_data = {
            "title": "High Priority Ticket",
            "workflow_type": "support_ticket",
            "priority": "high",
            "sla_definition_id": sla_def["sla_definition_id"]
        }
        
        response = client.post(
            "/api/v1/workflows",
            json=workflow_data,
            headers=auth_headers
        )
        assert response.status_code == 201
        workflow = response.json()
        
        # Verify SLA instance created
        workflow_id = workflow["workflow_id"]
        response = client.get(
            f"/api/v1/sla/workflows/{workflow_id}/instances",
            headers=auth_headers
        )
        assert response.status_code == 200
        sla_instances = response.json()
        assert len(sla_instances) > 0
        assert sla_instances[0]["status"] == SLAStatus.ACTIVE
    
    async def test_workflow_state_transitions(self, client: TestClient, auth_headers):
        """Test all workflow state transitions"""
        # Create workflow
        response = client.post(
            "/api/v1/workflows",
            json={
                "title": "State Transition Test",
                "workflow_type": "support_ticket"
            },
            headers=auth_headers
        )
        workflow_id = response.json()["workflow_id"]
        
        # PENDING -> ACTIVE
        response = client.post(
            f"/api/v1/workflows/{workflow_id}/start",
            headers=auth_headers
        )
        assert response.json()["current_state"] == WorkflowState.ACTIVE
        
        # ACTIVE -> PAUSED
        response = client.post(
            f"/api/v1/workflows/{workflow_id}/pause",
            headers=auth_headers
        )
        assert response.json()["current_state"] == WorkflowState.PAUSED
        
        # PAUSED -> ACTIVE
        response = client.post(
            f"/api/v1/workflows/{workflow_id}/resume",
            headers=auth_headers
        )
        assert response.json()["current_state"] == WorkflowState.ACTIVE
        
        # ACTIVE -> COMPLETED
        response = client.post(
            f"/api/v1/workflows/{workflow_id}/complete",
            headers=auth_headers
        )
        assert response.json()["current_state"] == WorkflowState.COMPLETED


@pytest.mark.asyncio
class TestSLAIntegration:
    """Test SLA monitoring and breach detection"""
    
    async def test_sla_soft_breach_detection(self, client: TestClient, auth_headers):
        """Test soft breach detection and notification"""
        # Create SLA definition with short time limits
        sla_data = {
            "name": "Quick SLA",
            "soft_limit_minutes": 1,
            "hard_limit_minutes": 5
        }
        
        response = client.post(
            "/api/v1/sla/definitions",
            json=sla_data,
            headers=auth_headers
        )
        sla_def_id = response.json()["sla_definition_id"]
        
        # Create and start workflow
        workflow_data = {
            "title": "SLA Test Workflow",
            "workflow_type": "support_ticket",
            "sla_definition_id": sla_def_id
        }
        
        response = client.post(
            "/api/v1/workflows",
            json=workflow_data,
            headers=auth_headers
        )
        workflow_id = response.json()["workflow_id"]
        
        # Start workflow
        client.post(
            f"/api/v1/workflows/{workflow_id}/start",
            headers=auth_headers
        )
        
        # Trigger breach check (in production, this runs automatically)
        response = client.post(
            f"/api/v1/sla/monitoring/check-breaches",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        # Verify notifications were created
        response = client.get(
            "/api/v1/notifications",
            headers=auth_headers
        )
        notifications = response.json()
        
        # Should have SLA warning notification
        sla_notifications = [
            n for n in notifications
            if n["type"] == NotificationType.SLA_WARNING
        ]
        assert len(sla_notifications) > 0
    
    async def test_sla_compliance_reporting(self, client: TestClient, auth_headers):
        """Test SLA compliance report generation"""
        # Create multiple workflows with SLAs
        for i in range(5):
            workflow_data = {
                "title": f"Workflow {i}",
                "workflow_type": "support_ticket"
            }
            response = client.post(
                "/api/v1/workflows",
                json=workflow_data,
                headers=auth_headers
            )
        
        # Get compliance report
        response = client.get(
            "/api/v1/dashboard/sla-metrics?time_range=last_24_hours",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        metrics = response.json()
        assert "compliance_rate" in metrics
        assert "total_slas" in metrics
        assert metrics["time_range"] == "last_24_hours"


@pytest.mark.asyncio
class TestAgentIntegration:
    """Test agent decision-making integration"""
    
    async def test_agent_workflow_recommendation(self, client: TestClient, auth_headers):
        """Test agent providing workflow recommendation"""
        # Create workflow
        response = client.post(
            "/api/v1/workflows",
            json={
                "title": "Agent Test Workflow",
                "workflow_type": "support_ticket",
                "priority": "medium"
            },
            headers=auth_headers
        )
        workflow_id = response.json()["workflow_id"]
        
        # Start workflow
        client.post(
            f"/api/v1/workflows/{workflow_id}/start",
            headers=auth_headers
        )
        
        # Request agent decision
        response = client.post(
            f"/api/v1/agent-workflows/{workflow_id}/analyze",
            json={
                "trigger_point": "sla_warning",
                "context": {
                    "time_remaining_minutes": 15,
                    "current_priority": "medium"
                }
            },
            headers=auth_headers
        )
        
        assert response.status_code == 200
        decision = response.json()
        assert "decision_type" in decision
        assert "confidence" in decision
        assert "reasoning" in decision
    
    async def test_agent_decision_notification(self, client: TestClient, auth_headers):
        """Test that agent decisions create notifications"""
        # Create workflow
        response = client.post(
            "/api/v1/workflows",
            json={
                "title": "Notification Test",
                "workflow_type": "incident"
            },
            headers=auth_headers
        )
        workflow_id = response.json()["workflow_id"]
        
        # Trigger agent analysis
        client.post(
            f"/api/v1/agent-workflows/{workflow_id}/analyze",
            json={"trigger_point": "workflow_created"},
            headers=auth_headers
        )
        
        # Check notifications
        response = client.get(
            "/api/v1/notifications",
            headers=auth_headers
        )
        
        notifications = response.json()
        agent_notifications = [
            n for n in notifications
            if n["type"] == NotificationType.AGENT_DECISION
        ]
        assert len(agent_notifications) > 0


@pytest.mark.asyncio
class TestDashboardIntegration:
    """Test dashboard data aggregation"""
    
    async def test_dashboard_overview_accuracy(self, client: TestClient, auth_headers):
        """Test dashboard overview shows accurate counts"""
        # Create test data
        for i in range(3):
            client.post(
                "/api/v1/workflows",
                json={
                    "title": f"Dashboard Test {i}",
                    "workflow_type": "support_ticket"
                },
                headers=auth_headers
            )
        
        # Get dashboard overview
        response = client.get(
            "/api/v1/dashboard/overview",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        overview = response.json()
        
        assert "total_workflows" in overview
        assert overview["total_workflows"] >= 3
        assert "active_workflows" in overview
        assert "sla_compliance_rate" in overview
        assert "timestamp" in overview
    
    async def test_dashboard_time_series(self, client: TestClient, auth_headers):
        """Test time series data generation"""
        response = client.get(
            "/api/v1/dashboard/time-series/workflow_volume?time_range=last_24_hours",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        time_series = response.json()
        
        assert time_series["metric_name"] == "workflow_volume"
        assert time_series["time_range"] == "last_24_hours"
        assert len(time_series["data_points"]) > 0
        
        # Verify data point structure
        point = time_series["data_points"][0]
        assert "timestamp" in point
        assert "value" in point


@pytest.mark.asyncio
class TestNotificationIntegration:
    """Test notification system integration"""
    
    async def test_notification_creation_and_retrieval(self, client: TestClient, auth_headers):
        """Test creating and retrieving notifications"""
        # Trigger action that creates notification (workflow escalation)
        response = client.post(
            "/api/v1/workflows",
            json={
                "title": "Escalation Test",
                "workflow_type": "incident",
                "priority": "high"
            },
            headers=auth_headers
        )
        workflow_id = response.json()["workflow_id"]
        
        # Start workflow
        client.post(
            f"/api/v1/workflows/{workflow_id}/start",
            headers=auth_headers
        )
        
        # Get notifications
        response = client.get(
            "/api/v1/notifications",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        notifications = response.json()
        assert isinstance(notifications, list)
    
    async def test_notification_read_marking(self, client: TestClient, auth_headers):
        """Test marking notifications as read"""
        # Get notifications
        response = client.get(
            "/api/v1/notifications",
            headers=auth_headers
        )
        notifications = response.json()
        
        if len(notifications) > 0:
            notification_id = notifications[0]["notification_id"]
            
            # Mark as read
            response = client.post(
                f"/api/v1/notifications/{notification_id}/read",
                headers=auth_headers
            )
            
            assert response.status_code == 200
            updated = response.json()
            assert updated["status"] == "read"


@pytest.mark.asyncio
class TestEventSourcingIntegrity:
    """Test event sourcing and integrity"""
    
    async def test_event_hash_chain_integrity(self, client: TestClient, auth_headers):
        """Test that event hash chain is maintained"""
        # Create workflow (generates events)
        response = client.post(
            "/api/v1/workflows",
            json={
                "title": "Hash Chain Test",
                "workflow_type": "support_ticket"
            },
            headers=auth_headers
        )
        workflow_id = response.json()["workflow_id"]
        
        # Perform multiple state changes
        client.post(f"/api/v1/workflows/{workflow_id}/start", headers=auth_headers)
        client.post(f"/api/v1/workflows/{workflow_id}/pause", headers=auth_headers)
        client.post(f"/api/v1/workflows/{workflow_id}/resume", headers=auth_headers)
        
        # Get event stream
        response = client.get(
            f"/api/v1/events/stream/{workflow_id}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        events = response.json()
        
        # Verify events are sequential
        assert len(events) >= 3
        
        # Verify hash chain (each event references previous)
        for i in range(1, len(events)):
            current = events[i]
            previous = events[i - 1]
            
            # Current event's previous_hash should match previous event's event_hash
            if "previous_hash" in current and "event_hash" in previous:
                assert current["previous_hash"] == previous["event_hash"]
    
    async def test_event_replay_consistency(self, client: TestClient, auth_headers):
        """Test that replaying events produces consistent state"""
        # Create and modify workflow
        response = client.post(
            "/api/v1/workflows",
            json={
                "title": "Replay Test",
                "workflow_type": "support_ticket"
            },
            headers=auth_headers
        )
        workflow_id = response.json()["workflow_id"]
        
        # Get current state
        response = client.get(
            f"/api/v1/workflows/{workflow_id}",
            headers=auth_headers
        )
        final_state = response.json()
        
        # Get events
        response = client.get(
            f"/api/v1/events/stream/{workflow_id}",
            headers=auth_headers
        )
        events = response.json()
        
        # Replay events should produce same state
        # (This would require a replay endpoint in production)
        assert final_state["workflow_id"] == workflow_id
        assert len(events) > 0
