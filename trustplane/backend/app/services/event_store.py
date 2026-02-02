"""
Event Store - Append-only, hash-chained event ledger

This is the CORE of the event-sourced architecture.
All state changes are recorded as immutable events.

Key properties:
1. APPEND-ONLY: Events can never be modified or deleted
2. HASH-CHAINED: Each event's hash includes the previous hash
3. IDEMPOTENT: Duplicate writes are safely rejected
4. REPLAYABLE: State can be rebuilt by replaying events

Why this matters:
- Complete audit trail for compliance
- Time-travel debugging
- Tamper detection via hash chain
- Disaster recovery via event replay
"""
from typing import List, Optional, Dict, Any, Callable, TypeVar
from uuid import UUID, uuid4
from datetime import datetime
from dataclasses import dataclass
import json
import hashlib
import logging

from app.models.event import Event, EventCreate, EventType
from app.core.exceptions import EventStoreError, IntegrityError
from app.db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class AppendResult:
    """Result of appending an event"""
    success: bool
    event: Optional[Event]
    was_duplicate: bool = False
    error: Optional[str] = None


class EventStore:
    """
    Append-only event store with cryptographic hash chaining.
    
    Hash Chain Design:
    ==================
    
    Event 1 (Genesis):
        hash = SHA256("0000...0000" + serialize(data))
        previous_hash = "0000...0000" (64 zeros)
    
    Event 2:
        hash = SHA256(event1.hash + serialize(data))
        previous_hash = event1.hash
    
    Event N:
        hash = SHA256(event[N-1].hash + serialize(data))
        previous_hash = event[N-1].hash
    
    Tampering Detection:
    ====================
    If ANY event is modified:
    1. Its hash no longer matches its content
    2. All subsequent events have invalid previous_hash
    3. Chain verification fails at the tampered event
    
    This provides:
    - Immutability proof
    - Tamper evidence
    - Audit integrity
    """
    
    # Genesis hash - 64 zeros (SHA-256 produces 64 hex chars)
    GENESIS_HASH = "0" * 64
    
    # Table name in Supabase
    TABLE_NAME = "events"
    
    def __init__(self):
        self._client = None
    
    @property
    def client(self):
        """Lazy-load Supabase client"""
        if self._client is None:
            self._client = get_supabase_client()
        return self._client
    
    # =========================================================
    # CORE OPERATIONS
    # =========================================================
    
    async def append(
        self,
        org_id: UUID,
        event: EventCreate,
        actor_id: Optional[UUID] = None,
        actor_type: str = "user"
    ) -> AppendResult:
        """
        Append an event to the store with hash chaining.
        
        This is the ONLY way to write to the event store.
        
        Args:
            org_id: Organization ID for tenant isolation
            event: Event data to append
            actor_id: ID of actor (user, system, agent)
            actor_type: Type of actor
        
        Returns:
            AppendResult with the created event or error
        
        Raises:
            EventStoreError: If append fails (not for duplicates)
        """
        try:
            # Check for idempotency - reject duplicates
            if event.idempotency_key:
                existing = await self._check_idempotency(org_id, event.idempotency_key)
                if existing:
                    logger.info(f"Duplicate event rejected: {event.idempotency_key}")
                    return AppendResult(
                        success=True,
                        event=existing,
                        was_duplicate=True
                    )
            
            # Get the latest event in this stream for hash chaining
            latest = await self._get_latest_event(org_id, event.stream_id)
            
            # Calculate version
            version = (latest.version + 1) if latest else 1
            
            # Get previous hash for chaining
            previous_hash = latest.hash if latest else self.GENESIS_HASH
            
            # Prepare event data for hashing
            event_data = self._prepare_event_data(event, version)
            
            # Calculate hash (chained to previous)
            event_hash = self._calculate_hash(previous_hash, event_data)
            
            # Build the complete event record
            event_record = {
                "id": str(uuid4()),
                "org_id": str(org_id),
                "stream_id": str(event.stream_id),
                "stream_type": self._get_stream_type(event.event_type),
                "event_type": event.event_type.value,
                "version": version,
                "data": event.data,
                "metadata": event.metadata,
                "hash": event_hash,
                "previous_hash": previous_hash,
                "actor_id": str(actor_id) if actor_id else str(event.actor_id) if event.actor_id else None,
                "actor_type": event.actor_type or actor_type,
                "occurred_at": datetime.utcnow().isoformat(),
                "recorded_at": datetime.utcnow().isoformat(),
                "idempotency_key": event.idempotency_key,
            }
            
            # Insert into database
            result = self.client.table(self.TABLE_NAME).insert(event_record).execute()
            
            if not result.data:
                raise EventStoreError("Failed to insert event")
            
            # Convert to Event model
            created_event = self._record_to_event(result.data[0])
            
            logger.info(
                f"Event appended: stream={event.stream_id} "
                f"type={event.event_type.value} version={version}"
            )
            
            # Dispatch event to handlers (async, fire-and-forget)
            await self._dispatch_event(created_event)
            
            return AppendResult(success=True, event=created_event)
            
        except IntegrityError:
            # Re-raise integrity errors
            raise
        except Exception as e:
            logger.error(f"Failed to append event: {e}")
            raise EventStoreError(f"Failed to append event: {str(e)}")
    
    async def get_stream(
        self,
        org_id: UUID,
        stream_id: UUID,
        from_version: int = 0,
        to_version: Optional[int] = None
    ) -> List[Event]:
        """
        Get all events for a stream in version order.
        
        This is the foundation of event replay.
        
        Args:
            org_id: Organization ID for tenant isolation
            stream_id: The aggregate/stream ID
            from_version: Start from this version (inclusive)
            to_version: End at this version (inclusive), or None for all
        
        Returns:
            List of events in version order
        """
        try:
            query = (
                self.client.table(self.TABLE_NAME)
                .select("*")
                .eq("org_id", str(org_id))
                .eq("stream_id", str(stream_id))
                .gte("version", from_version)
                .order("version", desc=False)
            )
            
            if to_version is not None:
                query = query.lte("version", to_version)
            
            result = query.execute()
            
            return [self._record_to_event(r) for r in result.data]
            
        except Exception as e:
            logger.error(f"Failed to get stream: {e}")
            raise EventStoreError(f"Failed to get stream: {str(e)}")
    
    async def get_event(
        self,
        org_id: UUID,
        event_id: UUID
    ) -> Optional[Event]:
        """Get a specific event by ID"""
        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .select("*")
                .eq("org_id", str(org_id))
                .eq("id", str(event_id))
                .single()
                .execute()
            )
            
            if result.data:
                return self._record_to_event(result.data)
            return None
            
        except Exception as e:
            if "No rows" in str(e):
                return None
            logger.error(f"Failed to get event: {e}")
            raise EventStoreError(f"Failed to get event: {str(e)}")
    
    async def get_events_by_type(
        self,
        org_id: UUID,
        event_type: EventType,
        limit: int = 100,
        offset: int = 0
    ) -> List[Event]:
        """Get events by type across all streams"""
        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .select("*")
                .eq("org_id", str(org_id))
                .eq("event_type", event_type.value)
                .order("occurred_at", desc=True)
                .range(offset, offset + limit - 1)
                .execute()
            )
            
            return [self._record_to_event(r) for r in result.data]
            
        except Exception as e:
            logger.error(f"Failed to get events by type: {e}")
            raise EventStoreError(f"Failed to get events by type: {str(e)}")
    
    # =========================================================
    # INTEGRITY VERIFICATION
    # =========================================================
    
    async def verify_integrity(
        self,
        org_id: UUID,
        stream_id: UUID
    ) -> Dict[str, Any]:
        """
        Verify the hash chain integrity for a stream.
        
        This is CRITICAL for detecting tampering.
        
        Returns a detailed integrity report:
        - valid: Overall chain validity
        - event_count: Number of events checked
        - broken_at: Index where chain breaks (if any)
        - details: Detailed verification results
        """
        events = await self.get_stream(org_id, stream_id)
        
        if not events:
            return {
                "valid": True,
                "event_count": 0,
                "message": "No events in stream",
                "verified_at": datetime.utcnow().isoformat()
            }
        
        # Verify chain
        for i, event in enumerate(events):
            # Check version sequence
            expected_version = i + 1
            if event.version != expected_version:
                return {
                    "valid": False,
                    "event_count": len(events),
                    "broken_at": i,
                    "error": f"Version gap: expected {expected_version}, got {event.version}",
                    "event_id": str(event.id),
                    "verified_at": datetime.utcnow().isoformat()
                }
            
            # Check previous hash
            if i == 0:
                expected_prev_hash = self.GENESIS_HASH
            else:
                expected_prev_hash = events[i - 1].hash
            
            if event.previous_hash != expected_prev_hash:
                return {
                    "valid": False,
                    "event_count": len(events),
                    "broken_at": i,
                    "error": f"Previous hash mismatch at version {event.version}",
                    "event_id": str(event.id),
                    "expected_prev_hash": expected_prev_hash[:16] + "...",
                    "actual_prev_hash": event.previous_hash[:16] + "...",
                    "verified_at": datetime.utcnow().isoformat()
                }
            
            # Verify event's own hash
            event_data = {
                "stream_id": str(event.stream_id),
                "event_type": event.event_type.value,
                "version": event.version,
                "data": event.data,
                "occurred_at": event.occurred_at.isoformat() if isinstance(event.occurred_at, datetime) else event.occurred_at,
            }
            expected_hash = self._calculate_hash(expected_prev_hash, event_data)
            
            if event.hash != expected_hash:
                return {
                    "valid": False,
                    "event_count": len(events),
                    "broken_at": i,
                    "error": f"Event hash mismatch at version {event.version} - POSSIBLE TAMPERING",
                    "event_id": str(event.id),
                    "verified_at": datetime.utcnow().isoformat()
                }
        
        return {
            "valid": True,
            "event_count": len(events),
            "first_hash": events[0].hash[:16] + "..." if events else None,
            "last_hash": events[-1].hash[:16] + "..." if events else None,
            "message": "Hash chain verified successfully",
            "verified_at": datetime.utcnow().isoformat()
        }
    
    # =========================================================
    # EVENT REPLAY
    # =========================================================
    
    async def replay(
        self,
        org_id: UUID,
        stream_id: UUID,
        handler: Callable[[Event, T], T],
        initial_state: T,
        from_version: int = 0
    ) -> T:
        """
        Replay events through a handler to rebuild state.
        
        This is the foundation of event sourcing - state is derived
        from replaying events, not stored directly.
        
        Args:
            org_id: Organization ID
            stream_id: Stream to replay
            handler: Function that takes (event, current_state) -> new_state
            initial_state: Starting state before any events
            from_version: Start replay from this version
        
        Returns:
            Final state after replaying all events
        
        Example:
            def workflow_handler(event: Event, state: dict) -> dict:
                if event.event_type == EventType.WORKFLOW_CREATED:
                    return {**state, "status": "created"}
                elif event.event_type == EventType.WORKFLOW_TRANSITIONED:
                    return {**state, "status": event.data["to_state"]}
                return state
            
            final_state = await event_store.replay(
                org_id, workflow_id,
                workflow_handler,
                {"status": "unknown"}
            )
        """
        events = await self.get_stream(org_id, stream_id, from_version)
        
        state = initial_state
        for event in events:
            state = handler(event, state)
        
        return state
    
    async def replay_to_snapshot(
        self,
        org_id: UUID,
        stream_id: UUID,
        handlers: Dict[EventType, Callable[[Event, Dict], Dict]],
        initial_state: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Replay events using type-specific handlers to build a snapshot.
        
        More convenient than replay() for complex aggregates.
        """
        if initial_state is None:
            initial_state = {}
        
        def combined_handler(event: Event, state: Dict) -> Dict:
            handler = handlers.get(event.event_type)
            if handler:
                return handler(event, state)
            return state
        
        return await self.replay(
            org_id, stream_id,
            combined_handler,
            initial_state
        )
    
    # =========================================================
    # HELPER METHODS
    # =========================================================
    
    def _calculate_hash(self, previous_hash: str, event_data: Dict) -> str:
        """
        Calculate SHA-256 hash chained to previous hash.
        
        Hash = SHA256(previous_hash + canonical_json(event_data))
        """
        # Canonical JSON serialization (sorted keys for determinism)
        canonical = json.dumps(event_data, sort_keys=True, default=str)
        
        # Combine with previous hash
        combined = f"{previous_hash}:{canonical}"
        
        # SHA-256 hash
        return hashlib.sha256(combined.encode('utf-8')).hexdigest()
    
    def _prepare_event_data(self, event: EventCreate, version: int) -> Dict:
        """Prepare event data for hashing"""
        return {
            "stream_id": str(event.stream_id),
            "event_type": event.event_type.value,
            "version": version,
            "data": event.data,
            "occurred_at": datetime.utcnow().isoformat(),
        }
    
    def _get_stream_type(self, event_type: EventType) -> str:
        """Extract stream type from event type"""
        # e.g., "workflow.created" -> "workflow"
        return event_type.value.split(".")[0]
    
    async def _get_latest_event(
        self,
        org_id: UUID,
        stream_id: UUID
    ) -> Optional[Event]:
        """Get the most recent event in a stream"""
        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .select("*")
                .eq("org_id", str(org_id))
                .eq("stream_id", str(stream_id))
                .order("version", desc=True)
                .limit(1)
                .execute()
            )
            
            if result.data:
                return self._record_to_event(result.data[0])
            return None
            
        except Exception as e:
            logger.error(f"Failed to get latest event: {e}")
            return None
    
    async def _check_idempotency(
        self,
        org_id: UUID,
        idempotency_key: str
    ) -> Optional[Event]:
        """Check if an event with this idempotency key already exists"""
        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .select("*")
                .eq("org_id", str(org_id))
                .eq("idempotency_key", idempotency_key)
                .limit(1)
                .execute()
            )
            
            if result.data:
                return self._record_to_event(result.data[0])
            return None
            
        except Exception:
            return None
    
    def _record_to_event(self, record: Dict) -> Event:
        """Convert database record to Event model"""
        return Event(
            id=UUID(record["id"]),
            org_id=UUID(record["org_id"]),
            stream_id=UUID(record["stream_id"]),
            event_type=EventType(record["event_type"]),
            version=record["version"],
            data=record["data"],
            metadata=record.get("metadata", {}),
            hash=record["hash"],
            previous_hash=record["previous_hash"],
            actor_id=UUID(record["actor_id"]) if record.get("actor_id") else None,
            actor_type=record.get("actor_type", "user"),
            occurred_at=record["occurred_at"],
            recorded_at=record["recorded_at"],
        )
    
    # =========================================================
    # QUERY HELPERS
    # =========================================================
    
    async def get_stream_count(self, org_id: UUID, stream_id: UUID) -> int:
        """Get the number of events in a stream"""
        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .select("id", count="exact")
                .eq("org_id", str(org_id))
                .eq("stream_id", str(stream_id))
                .execute()
            )
            return result.count or 0
        except Exception:
            return 0
    
    async def stream_exists(self, org_id: UUID, stream_id: UUID) -> bool:
        """Check if a stream has any events"""
        count = await self.get_stream_count(org_id, stream_id)
        return count > 0
    
    async def get_latest_version(self, org_id: UUID, stream_id: UUID) -> int:
        """Get the latest version number in a stream"""
        latest = await self._get_latest_event(org_id, stream_id)
        return latest.version if latest else 0
    
    # =========================================================
    # EVENT DISPATCHING
    # =========================================================
    
    async def _dispatch_event(self, event: Event) -> None:
        """
        Dispatch event to registered handlers.
        
        This enables event-driven choreography between domains
        (e.g., workflow events trigger SLA actions).
        
        Dispatching is fire-and-forget to not slow down writes.
        Handler failures are logged but don't affect the append.
        """
        try:
            # Import here to avoid circular imports
            from app.services.event_dispatcher import event_dispatcher
            
            result = await event_dispatcher.dispatch(event)
            
            if not result.success:
                logger.warning(
                    f"Event dispatch had failures: {result.handlers_failed} failed "
                    f"of {result.handlers_called} handlers for event {event.id}"
                )
        except Exception as e:
            # Log but don't raise - event is already persisted
            logger.error(f"Event dispatch failed: {e}", extra={"event_id": str(event.id)})


# Singleton instance
event_store = EventStore()
