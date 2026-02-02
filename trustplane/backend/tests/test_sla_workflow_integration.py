"""
Tests for SLA-Workflow Integration

These tests verify the event-driven coordination between
workflows and SLAs.
"""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.sla_workflow_coordinator import (
    SLAWorkflowCoordinator,
    sla_workflow_coordinator,
)
from app.services.event_dispatcher import (
    EventDispatcher,
    event_dispatcher,
)
from app.models.event import Event, EventType
from app.engines.sla_types import SLAStatus, SLAPriority


class TestEventDispatcher:
    """Tests for the event dispatcher"""
    
    @pytest.fixture
    def dispatcher(self):
        return EventDispatcher()
    
    @pytest.fixture
    def sample_event(self):
        return Event(
            id=uuid4(),
            org_id=uuid4(),
            stream_id=uuid4(),
            event_type=EventType.WORKFLOW_CREATED,
            version=1,
            data={"name": "Test Workflow"},
            metadata={},
            hash="abc123",
            previous_hash="000000",
            occurred_at=datetime.utcnow(),
            recorded_at=datetime.utcnow(),
        )
    
    @pytest.mark.asyncio
    async def test_register_handler(self, dispatcher):
        """Should register handlers correctly"""
        handler = AsyncMock()
        
        dispatcher.register(
            name="test_handler",
            handler=handler,
            event_types={EventType.WORKFLOW_CREATED}
        )
        
        handlers = dispatcher.get_handlers()
        assert len(handlers) == 1
        assert handlers[0]["name"] == "test_handler"
    
    @pytest.mark.asyncio
    async def test_dispatch_calls_matching_handlers(self, dispatcher, sample_event):
        """Should call handlers that match the event type"""
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        
        dispatcher.register(
            "handler1",
            handler1,
            event_types={EventType.WORKFLOW_CREATED}
        )
        dispatcher.register(
            "handler2",
            handler2,
            event_types={EventType.WORKFLOW_COMPLETED}  # Different type
        )
        
        result = await dispatcher.dispatch(sample_event)
        
        assert result.handlers_called == 1
        handler1.assert_called_once_with(sample_event)
        handler2.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_dispatch_all_handlers_on_empty_filter(self, dispatcher, sample_event):
        """Handlers with no event_types should receive all events"""
        handler = AsyncMock()
        
        dispatcher.register(
            "catch_all",
            handler,
            event_types=None  # No filter = all events
        )
        
        result = await dispatcher.dispatch(sample_event)
        
        assert result.handlers_called == 1
        handler.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handler_error_isolation(self, dispatcher, sample_event):
        """One handler failure should not affect others"""
        handler1 = AsyncMock(side_effect=Exception("Handler 1 failed"))
        handler2 = AsyncMock()
        
        dispatcher.register(
            "failing_handler",
            handler1,
            event_types={EventType.WORKFLOW_CREATED},
            priority=10  # Runs first
        )
        dispatcher.register(
            "working_handler",
            handler2,
            event_types={EventType.WORKFLOW_CREATED},
            priority=1
        )
        
        result = await dispatcher.dispatch(sample_event)
        
        assert result.handlers_called == 2
        assert result.handlers_succeeded == 1
        assert result.handlers_failed == 1
        # Second handler still called despite first failing
        handler2.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_priority_ordering(self, dispatcher, sample_event):
        """Handlers should be called in priority order (descending)"""
        call_order = []
        
        async def handler1(e):
            call_order.append("handler1")
        
        async def handler2(e):
            call_order.append("handler2")
        
        async def handler3(e):
            call_order.append("handler3")
        
        dispatcher.register("handler1", handler1, priority=1)
        dispatcher.register("handler2", handler2, priority=10)  # Highest
        dispatcher.register("handler3", handler3, priority=5)
        
        await dispatcher.dispatch(sample_event)
        
        assert call_order == ["handler2", "handler3", "handler1"]
    
    @pytest.mark.asyncio
    async def test_disable_handler(self, dispatcher, sample_event):
        """Disabled handlers should not be called"""
        handler = AsyncMock()
        
        dispatcher.register("test", handler)
        dispatcher.disable_handler("test")
        
        result = await dispatcher.dispatch(sample_event)
        
        assert result.handlers_called == 0
        handler.assert_not_called()
    
    def test_metrics_tracking(self, dispatcher):
        """Should track dispatch metrics"""
        metrics = dispatcher.get_metrics()
        
        assert "events_dispatched" in metrics
        assert "handlers_invoked" in metrics
        assert "handlers_succeeded" in metrics
        assert "handlers_failed" in metrics


class TestSLAWorkflowCoordinator:
    """Tests for SLA-Workflow coordination"""
    
    @pytest.fixture
    def coordinator(self):
        return SLAWorkflowCoordinator()
    
    @pytest.fixture
    def mock_sla_service(self):
        with patch("app.services.sla_workflow_coordinator.sla_service") as mock:
            yield mock
    
    @pytest.fixture
    def workflow_created_event(self):
        return Event(
            id=uuid4(),
            org_id=uuid4(),
            stream_id=uuid4(),  # workflow_id
            event_type=EventType.WORKFLOW_CREATED,
            version=1,
            data={
                "name": "Test Workflow",
                "sla_definition_id": str(uuid4()),
            },
            metadata={},
            hash="abc123",
            previous_hash="000000",
            occurred_at=datetime.utcnow(),
            recorded_at=datetime.utcnow(),
        )
    
    @pytest.mark.asyncio
    async def test_workflow_created_creates_sla_instance(
        self, coordinator, mock_sla_service, workflow_created_event
    ):
        """When workflow created with SLA, should create SLA instance"""
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_sla_service.create_instance = AsyncMock(return_value=mock_instance)
        
        await coordinator.handle_event(workflow_created_event)
        
        mock_sla_service.create_instance.assert_called_once()
        call_kwargs = mock_sla_service.create_instance.call_args.kwargs
        assert call_kwargs["workflow_id"] == workflow_created_event.stream_id
        assert call_kwargs["auto_start"] is False  # Started when workflow starts
    
    @pytest.mark.asyncio
    async def test_workflow_created_without_sla_skips(
        self, coordinator, mock_sla_service
    ):
        """Workflow without SLA definition should not create instance"""
        event = Event(
            id=uuid4(),
            org_id=uuid4(),
            stream_id=uuid4(),
            event_type=EventType.WORKFLOW_CREATED,
            version=1,
            data={"name": "No SLA Workflow"},  # No sla_definition_id
            metadata={},
            hash="abc123",
            previous_hash="000000",
            occurred_at=datetime.utcnow(),
            recorded_at=datetime.utcnow(),
        )
        
        await coordinator.handle_event(event)
        
        mock_sla_service.create_instance.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_workflow_started_starts_sla(
        self, coordinator, mock_sla_service
    ):
        """When workflow transitions pending→active, should start SLA"""
        # Setup mock SLA instance
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_instance.status = SLAStatus.PENDING
        mock_instance.is_terminal = MagicMock(return_value=False)
        mock_instance.is_paused = False
        
        mock_sla_service.get_instances_for_workflow = AsyncMock(return_value=[mock_instance])
        mock_sla_service.start_sla = AsyncMock(return_value=mock_instance)
        mock_sla_service.check_and_record_breach = AsyncMock(return_value=(MagicMock(), False))
        
        event = Event(
            id=uuid4(),
            org_id=uuid4(),
            stream_id=uuid4(),
            event_type=EventType.WORKFLOW_TRANSITIONED,
            version=2,
            data={"from_state": "pending", "to_state": "active"},
            metadata={},
            hash="abc123",
            previous_hash="000000",
            occurred_at=datetime.utcnow(),
            recorded_at=datetime.utcnow(),
        )
        
        await coordinator.handle_event(event)
        
        mock_sla_service.start_sla.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_workflow_paused_pauses_sla(
        self, coordinator, mock_sla_service
    ):
        """When workflow pauses, should pause SLA"""
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_instance.status = SLAStatus.ACTIVE
        mock_instance.is_terminal = MagicMock(return_value=False)
        mock_instance.is_paused = False
        
        mock_sla_service.get_instances_for_workflow = AsyncMock(return_value=[mock_instance])
        mock_sla_service.pause_sla = AsyncMock(return_value=mock_instance)
        mock_sla_service.check_and_record_breach = AsyncMock(return_value=(MagicMock(), False))
        
        event = Event(
            id=uuid4(),
            org_id=uuid4(),
            stream_id=uuid4(),
            event_type=EventType.WORKFLOW_TRANSITIONED,
            version=3,
            data={"from_state": "active", "to_state": "paused", "reason": "Waiting on customer"},
            metadata={},
            hash="abc123",
            previous_hash="000000",
            occurred_at=datetime.utcnow(),
            recorded_at=datetime.utcnow(),
        )
        
        await coordinator.handle_event(event)
        
        mock_sla_service.pause_sla.assert_called_once()
        call_kwargs = mock_sla_service.pause_sla.call_args.kwargs
        assert "Waiting on customer" in call_kwargs["reason"]
    
    @pytest.mark.asyncio
    async def test_workflow_resumed_resumes_sla(
        self, coordinator, mock_sla_service
    ):
        """When workflow resumes, should resume SLA"""
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_instance.status = SLAStatus.ACTIVE
        mock_instance.is_terminal = MagicMock(return_value=False)
        mock_instance.is_paused = True  # Currently paused
        
        mock_sla_service.get_instances_for_workflow = AsyncMock(return_value=[mock_instance])
        mock_sla_service.resume_sla = AsyncMock(return_value=mock_instance)
        mock_sla_service.check_and_record_breach = AsyncMock(return_value=(MagicMock(), False))
        
        event = Event(
            id=uuid4(),
            org_id=uuid4(),
            stream_id=uuid4(),
            event_type=EventType.WORKFLOW_TRANSITIONED,
            version=4,
            data={"from_state": "paused", "to_state": "active"},
            metadata={},
            hash="abc123",
            previous_hash="000000",
            occurred_at=datetime.utcnow(),
            recorded_at=datetime.utcnow(),
        )
        
        await coordinator.handle_event(event)
        
        mock_sla_service.resume_sla.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_workflow_completed_finalizes_sla(
        self, coordinator, mock_sla_service
    ):
        """When workflow completes, should finalize SLA"""
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_instance.status = SLAStatus.ACTIVE
        mock_instance.is_terminal = MagicMock(return_value=False)
        
        mock_sla_service.get_instances_for_workflow = AsyncMock(return_value=[mock_instance])
        mock_sla_service.complete_sla = AsyncMock(return_value=mock_instance)
        
        event = Event(
            id=uuid4(),
            org_id=uuid4(),
            stream_id=uuid4(),
            event_type=EventType.WORKFLOW_COMPLETED,
            version=5,
            data={},
            metadata={},
            hash="abc123",
            previous_hash="000000",
            occurred_at=datetime.utcnow(),
            recorded_at=datetime.utcnow(),
        )
        
        await coordinator.handle_event(event)
        
        mock_sla_service.complete_sla.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_workflow_cancelled_cancels_sla(
        self, coordinator, mock_sla_service
    ):
        """When workflow cancelled, should cancel SLA"""
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_instance.status = SLAStatus.ACTIVE
        mock_instance.is_terminal = MagicMock(return_value=False)
        
        mock_sla_service.get_instances_for_workflow = AsyncMock(return_value=[mock_instance])
        mock_sla_service.cancel_sla = AsyncMock(return_value=mock_instance)
        mock_sla_service.check_and_record_breach = AsyncMock(return_value=(MagicMock(), False))
        
        event = Event(
            id=uuid4(),
            org_id=uuid4(),
            stream_id=uuid4(),
            event_type=EventType.WORKFLOW_TRANSITIONED,
            version=6,
            data={"from_state": "active", "to_state": "cancelled", "reason": "User cancelled"},
            metadata={},
            hash="abc123",
            previous_hash="000000",
            occurred_at=datetime.utcnow(),
            recorded_at=datetime.utcnow(),
        )
        
        await coordinator.handle_event(event)
        
        mock_sla_service.cancel_sla.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handler_error_does_not_propagate(
        self, coordinator, mock_sla_service
    ):
        """Handler errors should be logged but not re-raised"""
        mock_sla_service.create_instance = AsyncMock(side_effect=Exception("DB error"))
        
        event = Event(
            id=uuid4(),
            org_id=uuid4(),
            stream_id=uuid4(),
            event_type=EventType.WORKFLOW_CREATED,
            version=1,
            data={"name": "Test", "sla_definition_id": str(uuid4())},
            metadata={},
            hash="abc123",
            previous_hash="000000",
            occurred_at=datetime.utcnow(),
            recorded_at=datetime.utcnow(),
        )
        
        # Should not raise
        await coordinator.handle_event(event)


class TestBatchBreachChecker:
    """Tests for batch breach checking"""
    
    @pytest.fixture
    def coordinator(self):
        return SLAWorkflowCoordinator()
    
    @pytest.fixture
    def mock_sla_service(self):
        with patch("app.services.sla_workflow_coordinator.sla_service") as mock:
            yield mock
    
    @pytest.mark.asyncio
    async def test_check_all_active_slas(self, coordinator, mock_sla_service):
        """Should check all active SLAs and return summary"""
        org_id = uuid4()
        
        # Setup mock instances
        instance1 = MagicMock()
        instance1.id = uuid4()
        instance1.workflow_id = uuid4()
        instance1.status = SLAStatus.ACTIVE
        
        instance2 = MagicMock()
        instance2.id = uuid4()
        instance2.workflow_id = uuid4()
        instance2.status = SLAStatus.ACTIVE
        
        mock_sla_service.list_active_instances = AsyncMock(return_value=[instance1, instance2])
        
        # No breaches
        breach_result = MagicMock()
        breach_result.is_soft_breached = False
        breach_result.is_hard_breached = False
        mock_sla_service.check_and_record_breach = AsyncMock(return_value=(breach_result, False))
        
        # Low risk prediction
        prediction = MagicMock()
        prediction.risk_level = "low"
        prediction.probability = 0.1
        prediction.time_remaining_seconds = 3600
        mock_sla_service.predict_breach = AsyncMock(return_value=prediction)
        
        results = await coordinator.check_all_active_slas(org_id)
        
        assert results["checked"] == 2
        assert results["new_soft_breaches"] == 0
        assert results["new_hard_breaches"] == 0
        assert len(results["at_risk"]) == 0
    
    @pytest.mark.asyncio
    async def test_detects_new_breaches(self, coordinator, mock_sla_service):
        """Should detect and count new breaches"""
        org_id = uuid4()
        
        instance = MagicMock()
        instance.id = uuid4()
        instance.workflow_id = uuid4()
        instance.status = SLAStatus.ACTIVE
        
        mock_sla_service.list_active_instances = AsyncMock(return_value=[instance])
        
        # Soft breach detected
        breach_result = MagicMock()
        breach_result.is_soft_breached = True
        breach_result.is_hard_breached = False
        mock_sla_service.check_and_record_breach = AsyncMock(return_value=(breach_result, True))
        
        prediction = MagicMock()
        prediction.risk_level = "high"
        prediction.probability = 0.8
        prediction.time_remaining_seconds = 300
        mock_sla_service.predict_breach = AsyncMock(return_value=prediction)
        
        results = await coordinator.check_all_active_slas(org_id)
        
        assert results["new_soft_breaches"] == 1
    
    @pytest.mark.asyncio
    async def test_identifies_at_risk_slas(self, coordinator, mock_sla_service):
        """Should identify high-risk SLAs"""
        org_id = uuid4()
        
        instance = MagicMock()
        instance.id = uuid4()
        instance.workflow_id = uuid4()
        instance.status = SLAStatus.ACTIVE
        
        mock_sla_service.list_active_instances = AsyncMock(return_value=[instance])
        
        # No breach yet
        breach_result = MagicMock()
        breach_result.is_soft_breached = False
        breach_result.is_hard_breached = False
        mock_sla_service.check_and_record_breach = AsyncMock(return_value=(breach_result, False))
        
        # High risk
        prediction = MagicMock()
        prediction.risk_level = "critical"
        prediction.probability = 0.95
        prediction.time_remaining_seconds = 60
        mock_sla_service.predict_breach = AsyncMock(return_value=prediction)
        
        results = await coordinator.check_all_active_slas(org_id)
        
        assert len(results["at_risk"]) == 1
        assert results["at_risk"][0]["risk_level"] == "critical"
