"""
Event Store Service - Core of event sourcing
"""
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime

from app.models.event import Event, EventCreate, EventType
from app.core.security import generate_hash, chain_hash


class EventStore:
    """
    Append-only event store with hash chaining.
    Will be implemented with Supabase Postgres.
    """
    
    GENESIS_HASH = "0" * 64  # Genesis hash for first event in stream
    
    async def append(
        self,
        org_id: UUID,
        event: EventCreate
    ) -> Event:
        """
        Append event to store with hash chaining.
        Idempotent - duplicate idempotency_key is rejected.
        """
        # Placeholder - will be implemented with Supabase
        raise NotImplementedError("Will be implemented in Step 5")
    
    async def get_stream(
        self,
        org_id: UUID,
        stream_id: UUID,
        from_version: int = 0
    ) -> List[Event]:
        """Get all events for a stream, optionally from a specific version"""
        raise NotImplementedError("Will be implemented in Step 5")
    
    async def get_event(
        self,
        org_id: UUID,
        event_id: UUID
    ) -> Optional[Event]:
        """Get a specific event by ID"""
        raise NotImplementedError("Will be implemented in Step 5")
    
    async def verify_integrity(
        self,
        org_id: UUID,
        stream_id: UUID
    ) -> bool:
        """Verify hash chain integrity for a stream"""
        raise NotImplementedError("Will be implemented in Step 5")
    
    async def replay(
        self,
        org_id: UUID,
        stream_id: UUID,
        handler: callable
    ) -> Any:
        """Replay events through a handler to rebuild state"""
        raise NotImplementedError("Will be implemented in Step 5")


# Singleton instance
event_store = EventStore()
