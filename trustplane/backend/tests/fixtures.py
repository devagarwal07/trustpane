"""
Test Fixtures and Factories

Provides reusable test data and mock objects for testing.
"""
import pytest
from uuid import UUID, uuid4
from datetime import datetime, timedelta
from typing import Dict, Any, List

from app.models.workflow import WorkflowState, WorkflowType
from app.models.sla import SLAStatus
from app.models.event import EventCreate, EventType
from app.models.notification import NotificationChannel, NotificationPriority, NotificationStatus
from app.services.workflow_service import WorkflowStateMachine


class TestDataFactory:
    """Factory for creating test data"""
    
    @staticmethod
    def create_org_id() -> UUID:
        """Create a test organization ID"""
        return uuid4()
    
    @staticmethod
    def create_user_id() -> UUID:
        """Create a test user ID"""
        return uuid4()
    
    @staticmethod
    def create_workflow_id() -> UUID:
        """Create a test workflow ID"""
        return uuid4()
    
    @staticmethod
    def create_workflow_payload(
        org_id: UUID,
        workflow_type: WorkflowType = WorkflowType.SUPPORT_TICKET,
        priority: str = "medium",
        assignee_id: UUID = None
    ) -> Dict[str, Any]:
        """Create workflow creation payload"""
        return {
            "title": "Test Workflow",
            "description": "Test workflow description",
            "workflow_type": workflow_type,
            "priority": priority,
            "assignee_id": str(assignee_id) if assignee_id else None,
            "metadata": {
                "customer_id": "cust_123",
                "source": "api"
            }
        }
    
    @staticmethod
    def create_sla_definition(
        org_id: UUID,
        soft_limit: int = 60,
        hard_limit: int = 120
    ) -> Dict[str, Any]:
        """Create SLA definition payload"""
        return {
            "name": "Test SLA",
            "description": "Test SLA definition",
            "soft_limit_minutes": soft_limit,
            "hard_limit_minutes": hard_limit,
            "conditions": {
                "priority": ["high", "critical"]
            },
            "penalty_config": {
                "soft_penalty": 100,
                "hard_penalty": 500
            },
            "notification_config": {
                "notify_on_soft": True,
                "notify_on_hard": True
            }
        }
    
    @staticmethod
    def create_event(
        org_id: UUID,
        stream_id: UUID,
        event_type: str,
        payload: Dict[str, Any],
        user_id: UUID = None
    ) -> EventCreate:
        """Create an event"""
        return EventCreate(
            org_id=org_id,
            stream_id=stream_id,
            stream_type="workflow",
            event_type=event_type,
            payload=payload,
            user_id=user_id or uuid4(),
            occurred_at=datetime.utcnow()
        )
    
    @staticmethod
    def create_notification_payload(
        org_id: UUID,
        user_id: UUID,
        notification_type: str = "SLA_WARNING",
        priority: NotificationPriority = NotificationPriority.NORMAL
    ) -> Dict[str, Any]:
        """Create notification payload"""
        return {
            "type": notification_type,
            "title": "Test Notification",
            "message": "This is a test notification",
            "priority": priority,
            "channels": [NotificationChannel.IN_APP],
            "metadata": {
                "workflow_id": str(uuid4()),
                "source": "test"
            }
        }
    
    @staticmethod
    def create_agent_decision(
        workflow_id: UUID,
        decision_type: str = "escalate",
        confidence: float = 0.85
    ) -> Dict[str, Any]:
        """Create agent decision payload"""
        return {
            "decision_type": decision_type,
            "confidence": confidence,
            "reasoning": "Test agent reasoning",
            "recommended_action": {
                "action": "escalate",
                "target_priority": "high",
                "reason": "SLA breach risk"
            },
            "metadata": {
                "model": "gpt-4",
                "context_tokens": 1500
            }
        }


@pytest.fixture
def test_factory():
    """Test data factory fixture"""
    return TestDataFactory()


@pytest.fixture
def org_id():
    """Organization ID fixture"""
    return uuid4()


@pytest.fixture
def user_id():
    """User ID fixture"""
    return uuid4()


@pytest.fixture
def workflow_id():
    """Workflow ID fixture"""
    return uuid4()


@pytest.fixture
def workflow_payload(org_id, user_id):
    """Workflow creation payload fixture"""
    return TestDataFactory.create_workflow_payload(org_id, assignee_id=user_id)


@pytest.fixture
def sla_definition(org_id):
    """SLA definition fixture"""
    return TestDataFactory.create_sla_definition(org_id)


@pytest.fixture
def mock_supabase_client():
    """Mock Supabase client"""
    class MockQuery:
        def __init__(self):
            self.data = []
            self.count = 0
        
        def select(self, *args, **kwargs):
            return self
        
        def insert(self, *args, **kwargs):
            return self
        
        def update(self, *args, **kwargs):
            return self
        
        def delete(self, *args, **kwargs):
            return self
        
        def eq(self, *args, **kwargs):
            return self
        
        def neq(self, *args, **kwargs):
            return self
        
        def like(self, *args, **kwargs):
            return self
        
        def ilike(self, *args, **kwargs):
            return self
        
        def gte(self, *args, **kwargs):
            return self
        
        def lte(self, *args, **kwargs):
            return self
        
        def order(self, *args, **kwargs):
            return self
        
        def limit(self, *args, **kwargs):
            return self
        
        def execute(self):
            return self
    
    class MockClient:
        def table(self, name: str):
            return MockQuery()
        
        def auth(self):
            return self
        
        def sign_in(self, *args, **kwargs):
            return {"user": {"id": str(uuid4())}}
    
    return MockClient()


@pytest.fixture
def mock_workflow_service(org_id):
    """Mock workflow service"""
    from app.services.workflow_service import WorkflowService
    return WorkflowService(org_id)


@pytest.fixture
def mock_sla_service(org_id):
    """Mock SLA service"""
    from app.services.sla_service import SLAService
    return SLAService(org_id)


@pytest.fixture
def mock_notification_service(org_id):
    """Mock notification service"""
    from app.services.notification_service import NotificationService
    return NotificationService(org_id)


@pytest.fixture
def sample_workflow_events(org_id, workflow_id, user_id):
    """Sample workflow event sequence"""
    return [
        EventCreate(
            org_id=org_id,
            stream_id=workflow_id,
            stream_type="workflow",
            event_type="workflow.created",
            payload={
                "title": "Test Workflow",
                "workflow_type": WorkflowType.SUPPORT_TICKET,
                "current_state": WorkflowState.PENDING
            },
            user_id=user_id,
            occurred_at=datetime.utcnow()
        ),
        EventCreate(
            org_id=org_id,
            stream_id=workflow_id,
            stream_type="workflow",
            event_type="workflow.started",
            payload={
                "current_state": WorkflowState.ACTIVE,
                "previous_state": WorkflowState.PENDING
            },
            user_id=user_id,
            occurred_at=datetime.utcnow() + timedelta(minutes=1)
        )
    ]


@pytest.fixture
def auth_headers(user_id, org_id):
    """Create mock auth headers"""
    import jwt
    from datetime import datetime, timedelta
    
    # Create a mock JWT token
    payload = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "email": "test@example.com",
        "role": "admin",
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    
    # Use a test secret
    token = jwt.encode(payload, "test_secret", algorithm="HS256")
    
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }


@pytest.fixture
async def sample_workflow_state(mock_workflow_service, org_id, workflow_id, user_id):
    """Create a sample workflow in the system"""
    # This fixture would actually create a workflow in the test database
    # For now, it returns the expected structure
    return {
        "workflow_id": workflow_id,
        "org_id": org_id,
        "current_state": WorkflowState.ACTIVE,
        "workflow_type": WorkflowType.SUPPORT_TICKET,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "metadata": {}
    }


@pytest.fixture
def time_series_data():
    """Sample time series data for testing"""
    now = datetime.utcnow()
    return [
        {"timestamp": now - timedelta(hours=i), "value": 10 + i}
        for i in range(24)
    ]


@pytest.fixture(autouse=True)
async def cleanup_test_data():
    """Cleanup test data after each test"""
    yield
    # Cleanup logic would go here
    # For now, this is a placeholder
    pass
