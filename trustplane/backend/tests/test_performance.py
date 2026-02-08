"""
Performance Tests

Tests system performance under load, including:
- Event store write throughput
- Query performance
- Dashboard aggregation speed
- Concurrent request handling
"""
import pytest
import asyncio
from uuid import uuid4
from datetime import datetime
import time
from typing import List

from app.services.event_store import event_store
from app.models.event import EventCreate
from tests.fixtures import TestDataFactory


@pytest.mark.asyncio
@pytest.mark.performance
class TestEventStorePerformance:
    """Test event store performance"""
    
    async def test_bulk_event_append_throughput(self):
        """Test throughput for bulk event appends"""
        org_id = uuid4()
        stream_id = uuid4()
        user_id = uuid4()
        
        # Create 1000 events
        events = []
        for i in range(1000):
            event = EventCreate(
                org_id=org_id,
                stream_id=stream_id,
                stream_type="workflow",
                event_type="workflow.test_event",
                payload={"index": i, "data": f"test_{i}"},
                user_id=user_id,
                occurred_at=datetime.utcnow()
            )
            events.append(event)
        
        # Measure append time
        start_time = time.time()
        
        for event in events:
            await event_store.append(event)
        
        end_time = time.time()
        duration = end_time - start_time
        throughput = len(events) / duration
        
        print(f"\nBulk append: {len(events)} events in {duration:.2f}s")
        print(f"Throughput: {throughput:.0f} events/second")
        
        # Should handle at least 100 events/second
        assert throughput > 100
    
    async def test_concurrent_stream_writes(self):
        """Test concurrent writes to different streams"""
        org_id = uuid4()
        user_id = uuid4()
        
        # Create 10 concurrent streams with 100 events each
        async def write_stream(stream_id: uuid4):
            for i in range(100):
                event = EventCreate(
                    org_id=org_id,
                    stream_id=stream_id,
                    stream_type="workflow",
                    event_type="workflow.test",
                    payload={"index": i},
                    user_id=user_id,
                    occurred_at=datetime.utcnow()
                )
                await event_store.append(event)
        
        # Run concurrent writes
        start_time = time.time()
        
        tasks = [write_stream(uuid4()) for _ in range(10)]
        await asyncio.gather(*tasks)
        
        end_time = time.time()
        duration = end_time - start_time
        total_events = 10 * 100
        throughput = total_events / duration
        
        print(f"\nConcurrent writes: {total_events} events across 10 streams in {duration:.2f}s")
        print(f"Throughput: {throughput:.0f} events/second")
        
        # Should handle concurrent writes efficiently
        assert throughput > 200
    
    async def test_event_query_performance(self):
        """Test event query performance"""
        org_id = uuid4()
        stream_id = uuid4()
        user_id = uuid4()
        
        # Populate stream with 500 events
        for i in range(500):
            event = EventCreate(
                org_id=org_id,
                stream_id=stream_id,
                stream_type="workflow",
                event_type="workflow.test",
                payload={"index": i},
                user_id=user_id,
                occurred_at=datetime.utcnow()
            )
            await event_store.append(event)
        
        # Measure query time
        start_time = time.time()
        
        events = await event_store.get_stream(stream_id, org_id)
        
        end_time = time.time()
        query_time = (end_time - start_time) * 1000  # Convert to ms
        
        print(f"\nQuery {len(events)} events in {query_time:.0f}ms")
        
        # Should retrieve 500 events in under 100ms
        assert query_time < 100
        assert len(events) == 500


@pytest.mark.asyncio
@pytest.mark.performance
class TestWorkflowPerformance:
    """Test workflow service performance"""
    
    async def test_workflow_creation_rate(self):
        """Test workflow creation throughput"""
        from app.services.workflow_service import WorkflowService
        from app.models.workflow import WorkflowType
        
        org_id = uuid4()
        service = WorkflowService(org_id)
        
        # Create 100 workflows
        start_time = time.time()
        
        workflows = []
        for i in range(100):
            workflow = await service.create_workflow(
                title=f"Test Workflow {i}",
                workflow_type=WorkflowType.SUPPORT_TICKET,
                user_id=uuid4()
            )
            workflows.append(workflow)
        
        end_time = time.time()
        duration = end_time - start_time
        throughput = len(workflows) / duration
        
        print(f"\nCreated {len(workflows)} workflows in {duration:.2f}s")
        print(f"Throughput: {throughput:.0f} workflows/second")
        
        # Should create at least 20 workflows/second
        assert throughput > 20
    
    async def test_workflow_state_transition_performance(self):
        """Test state transition performance"""
        from app.services.workflow_service import WorkflowService
        from app.models.workflow import WorkflowType
        
        org_id = uuid4()
        user_id = uuid4()
        service = WorkflowService(org_id)
        
        # Create workflow
        workflow = await service.create_workflow(
            title="Transition Test",
            workflow_type=WorkflowType.SUPPORT_TICKET,
            user_id=user_id
        )
        
        # Measure 100 state transitions
        start_time = time.time()
        
        for i in range(50):
            await service.start_workflow(workflow.workflow_id, user_id)
            await service.pause_workflow(workflow.workflow_id, user_id)
        
        end_time = time.time()
        duration = end_time - start_time
        transitions = 100  # 50 starts + 50 pauses
        rate = transitions / duration
        
        print(f"\n{transitions} state transitions in {duration:.2f}s")
        print(f"Rate: {rate:.0f} transitions/second")
        
        # Should handle at least 50 transitions/second
        assert rate > 50


@pytest.mark.asyncio
@pytest.mark.performance
class TestDashboardPerformance:
    """Test dashboard aggregation performance"""
    
    async def test_dashboard_overview_response_time(self):
        """Test dashboard overview generation speed"""
        from app.services.dashboard_service import DashboardService
        from app.services.workflow_service import WorkflowService
        from app.services.sla_service import SLAService
        from app.services.notification_service import NotificationService
        
        org_id = uuid4()
        
        workflow_service = WorkflowService(org_id)
        sla_service = SLAService(org_id)
        notification_service = NotificationService(org_id)
        
        dashboard = DashboardService(
            org_id,
            workflow_service,
            sla_service,
            notification_service
        )
        
        # Measure overview generation
        start_time = time.time()
        
        overview = await dashboard.get_overview()
        
        end_time = time.time()
        response_time = (end_time - start_time) * 1000  # Convert to ms
        
        print(f"\nDashboard overview generated in {response_time:.0f}ms")
        
        # Should generate overview in under 500ms
        assert response_time < 500
        assert overview is not None
    
    async def test_sla_metrics_aggregation_speed(self):
        """Test SLA metrics aggregation performance"""
        from app.services.dashboard_service import DashboardService
        from app.services.workflow_service import WorkflowService
        from app.services.sla_service import SLAService
        from app.services.notification_service import NotificationService
        from app.models.dashboard import TimeRange
        
        org_id = uuid4()
        
        workflow_service = WorkflowService(org_id)
        sla_service = SLAService(org_id)
        notification_service = NotificationService(org_id)
        
        dashboard = DashboardService(
            org_id,
            workflow_service,
            sla_service,
            notification_service
        )
        
        # Measure SLA metrics aggregation
        start_time = time.time()
        
        metrics = await dashboard.get_sla_metrics(TimeRange.LAST_7_DAYS)
        
        end_time = time.time()
        aggregation_time = (end_time - start_time) * 1000
        
        print(f"\nSLA metrics aggregated in {aggregation_time:.0f}ms")
        
        # Should aggregate in under 1 second
        assert aggregation_time < 1000
        assert metrics is not None


@pytest.mark.asyncio
@pytest.mark.performance
class TestConcurrentRequests:
    """Test system under concurrent load"""
    
    async def test_concurrent_workflow_creation(self):
        """Test handling concurrent workflow creations"""
        from app.services.workflow_service import WorkflowService
        from app.models.workflow import WorkflowType
        
        org_id = uuid4()
        service = WorkflowService(org_id)
        
        # Create 50 workflows concurrently
        async def create_workflow(index: int):
            return await service.create_workflow(
                title=f"Concurrent Test {index}",
                workflow_type=WorkflowType.SUPPORT_TICKET,
                user_id=uuid4()
            )
        
        start_time = time.time()
        
        tasks = [create_workflow(i) for i in range(50)]
        workflows = await asyncio.gather(*tasks)
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"\nCreated {len(workflows)} workflows concurrently in {duration:.2f}s")
        
        assert len(workflows) == 50
        assert duration < 5  # Should complete in under 5 seconds
    
    async def test_concurrent_state_transitions(self):
        """Test concurrent state transitions on different workflows"""
        from app.services.workflow_service import WorkflowService
        from app.models.workflow import WorkflowType
        
        org_id = uuid4()
        user_id = uuid4()
        service = WorkflowService(org_id)
        
        # Create 20 workflows
        workflows = []
        for i in range(20):
            workflow = await service.create_workflow(
                title=f"Concurrent Transition {i}",
                workflow_type=WorkflowType.SUPPORT_TICKET,
                user_id=user_id
            )
            workflows.append(workflow)
        
        # Transition all concurrently
        async def transition_workflow(workflow):
            await service.start_workflow(workflow.workflow_id, user_id)
            await service.pause_workflow(workflow.workflow_id, user_id)
            await service.resume_workflow(workflow.workflow_id, user_id)
        
        start_time = time.time()
        
        tasks = [transition_workflow(w) for w in workflows]
        await asyncio.gather(*tasks)
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"\n{len(workflows) * 3} concurrent transitions in {duration:.2f}s")
        
        assert duration < 10  # Should complete in under 10 seconds


@pytest.mark.asyncio
@pytest.mark.performance
class TestMemoryUsage:
    """Test memory efficiency"""
    
    async def test_large_event_stream_memory(self):
        """Test memory usage when loading large event streams"""
        import sys
        
        org_id = uuid4()
        stream_id = uuid4()
        user_id = uuid4()
        
        # Create 1000 events
        for i in range(1000):
            event = EventCreate(
                org_id=org_id,
                stream_id=stream_id,
                stream_type="workflow",
                event_type="workflow.test",
                payload={"index": i, "data": "x" * 100},  # 100 chars per event
                user_id=user_id,
                occurred_at=datetime.utcnow()
            )
            await event_store.append(event)
        
        # Load stream and measure
        events = await event_store.get_stream(stream_id, org_id)
        
        # Calculate approximate memory usage
        event_size = sys.getsizeof(events[0].__dict__)
        total_size = event_size * len(events)
        total_mb = total_size / (1024 * 1024)
        
        print(f"\nLoaded {len(events)} events, ~{total_mb:.2f}MB")
        
        # Should be reasonably efficient
        assert total_mb < 50  # Less than 50MB for 1000 events
