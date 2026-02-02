"""
Tests for Event Store
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4
from datetime import datetime

from app.services.event_store import EventStore, AppendResult
from app.models.event import EventCreate, EventType
from app.core.exceptions import EventStoreError


class TestEventStoreHashing:
    """Tests for hash chain calculations"""
    
    def setup_method(self):
        self.event_store = EventStore()
    
    def test_genesis_hash_is_64_zeros(self):
        """Genesis hash should be 64 zeros"""
        assert self.event_store.GENESIS_HASH == "0" * 64
        assert len(self.event_store.GENESIS_HASH) == 64
    
    def test_hash_is_deterministic(self):
        """Same input should produce same hash"""
        event_data = {
            "stream_id": str(uuid4()),
            "event_type": "workflow.created",
            "version": 1,
            "data": {"name": "Test"},
            "occurred_at": "2026-01-01T00:00:00",
        }
        
        hash1 = self.event_store._calculate_hash(
            self.event_store.GENESIS_HASH,
            event_data
        )
        hash2 = self.event_store._calculate_hash(
            self.event_store.GENESIS_HASH,
            event_data
        )
        
        assert hash1 == hash2
    
    def test_hash_changes_with_different_data(self):
        """Different data should produce different hash"""
        data1 = {"name": "Test1"}
        data2 = {"name": "Test2"}
        
        hash1 = self.event_store._calculate_hash(
            self.event_store.GENESIS_HASH,
            data1
        )
        hash2 = self.event_store._calculate_hash(
            self.event_store.GENESIS_HASH,
            data2
        )
        
        assert hash1 != hash2
    
    def test_hash_changes_with_different_previous_hash(self):
        """Chain linking: different previous hash = different result"""
        event_data = {"name": "Test"}
        
        hash1 = self.event_store._calculate_hash(
            self.event_store.GENESIS_HASH,
            event_data
        )
        hash2 = self.event_store._calculate_hash(
            "a" * 64,  # Different previous hash
            event_data
        )
        
        assert hash1 != hash2
    
    def test_hash_is_sha256_length(self):
        """Hash should be 64 characters (SHA-256 hex)"""
        hash_result = self.event_store._calculate_hash(
            self.event_store.GENESIS_HASH,
            {"test": "data"}
        )
        
        assert len(hash_result) == 64
        # Should be valid hex
        int(hash_result, 16)


class TestEventStoreStreamType:
    """Tests for stream type extraction"""
    
    def setup_method(self):
        self.event_store = EventStore()
    
    def test_workflow_event_type(self):
        """Should extract 'workflow' from workflow events"""
        assert self.event_store._get_stream_type(EventType.WORKFLOW_CREATED) == "workflow"
        assert self.event_store._get_stream_type(EventType.WORKFLOW_TRANSITIONED) == "workflow"
    
    def test_sla_event_type(self):
        """Should extract 'sla' from SLA events"""
        assert self.event_store._get_stream_type(EventType.SLA_STARTED) == "sla"
        assert self.event_store._get_stream_type(EventType.SLA_HARD_BREACH) == "sla"
    
    def test_agent_event_type(self):
        """Should extract 'agent' from agent events"""
        assert self.event_store._get_stream_type(EventType.AGENT_DECISION) == "agent"


class TestEventStorePrepareData:
    """Tests for event data preparation"""
    
    def setup_method(self):
        self.event_store = EventStore()
    
    def test_prepare_event_data(self):
        """Should prepare event data correctly"""
        stream_id = uuid4()
        event = EventCreate(
            stream_id=stream_id,
            event_type=EventType.WORKFLOW_CREATED,
            data={"name": "Test Workflow"},
            metadata={"source": "test"},
        )
        
        prepared = self.event_store._prepare_event_data(event, version=1)
        
        assert prepared["stream_id"] == str(stream_id)
        assert prepared["event_type"] == "workflow.created"
        assert prepared["version"] == 1
        assert prepared["data"] == {"name": "Test Workflow"}
        assert "occurred_at" in prepared


class TestIntegrityVerification:
    """Tests for integrity verification"""
    
    @pytest.fixture
    def mock_events(self):
        """Create a chain of mock events"""
        event_store = EventStore()
        events = []
        
        stream_id = uuid4()
        org_id = uuid4()
        
        for i in range(3):
            version = i + 1
            prev_hash = events[-1]["hash"] if events else event_store.GENESIS_HASH
            
            event_data = {
                "stream_id": str(stream_id),
                "event_type": "workflow.created" if i == 0 else "workflow.transitioned",
                "version": version,
                "data": {"step": i},
                "occurred_at": f"2026-01-0{i+1}T00:00:00",
            }
            
            event_hash = event_store._calculate_hash(prev_hash, event_data)
            
            events.append({
                "id": str(uuid4()),
                "org_id": str(org_id),
                "stream_id": str(stream_id),
                "event_type": event_data["event_type"],
                "version": version,
                "data": event_data["data"],
                "hash": event_hash,
                "previous_hash": prev_hash,
                "occurred_at": event_data["occurred_at"],
            })
        
        return events
    
    def test_valid_chain_passes(self, mock_events):
        """Valid chain should pass verification"""
        from app.engines.integrity_engine import integrity_engine
        
        report = integrity_engine.verify_chain(mock_events)
        
        assert report.is_valid is True
        assert len(report.violations) == 0
    
    def test_broken_chain_fails(self, mock_events):
        """Broken chain should fail verification"""
        from app.engines.integrity_engine import integrity_engine
        
        # Break the chain by modifying a hash
        mock_events[1]["previous_hash"] = "broken_hash"
        
        report = integrity_engine.verify_chain(mock_events)
        
        assert report.is_valid is False
        assert len(report.violations) > 0
        assert report.violations[0].violation_type == "CHAIN_BROKEN"
    
    def test_version_gap_detected(self, mock_events):
        """Version gaps should be detected"""
        from app.engines.integrity_engine import integrity_engine
        
        # Create a version gap
        mock_events[1]["version"] = 5  # Should be 2
        
        report = integrity_engine.verify_chain(mock_events)
        
        assert report.is_valid is False
        assert any(v.violation_type == "VERSION_GAP" for v in report.violations)
