"""
SLA Service - Event-Sourced SLA Management

This service follows the event-sourcing pattern established in the event_store.
All SLA state changes are captured as events - enabling full audit trail,
time travel debugging, and integrity verification.

Event Flow:
    sla_definition.created -> sla_instance.created -> sla_instance.started
    -> (sla_instance.paused <-> sla_instance.resumed)* 
    -> sla_instance.completed | sla_instance.breached | sla_instance.cancelled
"""
from typing import Optional, Dict, Any, List, Tuple
from uuid import UUID, uuid4
from datetime import datetime, timedelta
import logging

from app.core.database import get_db_connection
from app.services.event_store import event_store
from app.engines.sla_engine import (
    SLAEngine, sla_engine, SLATimer, BreachCheckResult, BreachPrediction
)
from app.engines.sla_types import (
    SLADefinition, SLAInstance, SLAStatus, SLAPriority,
    BusinessHoursConfig, EscalationConfig, DEFAULT_SLA_TEMPLATES
)

logger = logging.getLogger(__name__)


# Event Types for SLA domain
class SLAEventType:
    # Definition events
    DEFINITION_CREATED = "sla.definition.created"
    DEFINITION_UPDATED = "sla.definition.updated"
    DEFINITION_ARCHIVED = "sla.definition.archived"
    
    # Instance events
    INSTANCE_CREATED = "sla.instance.created"
    INSTANCE_STARTED = "sla.instance.started"
    INSTANCE_PAUSED = "sla.instance.paused"
    INSTANCE_RESUMED = "sla.instance.resumed"
    INSTANCE_COMPLETED = "sla.instance.completed"  # Met the SLA
    INSTANCE_CANCELLED = "sla.instance.cancelled"
    
    # Breach events
    SOFT_BREACH_DETECTED = "sla.breach.soft_detected"
    HARD_BREACH_DETECTED = "sla.breach.hard_detected"
    BREACH_ACKNOWLEDGED = "sla.breach.acknowledged"
    
    # Escalation events
    ESCALATION_TRIGGERED = "sla.escalation.triggered"
    ESCALATION_RESOLVED = "sla.escalation.resolved"


class SLAService:
    """
    Event-sourced SLA service.
    
    All mutations go through the event store, state is derived by replay.
    This enables:
    - Complete audit trail of all SLA state changes
    - Time travel queries (SLA status at any point in time)
    - Integrity verification via hash chains
    - Replay and recovery
    """
    
    def __init__(self, engine: SLAEngine = None):
        self.engine = engine or sla_engine
    
    # =========================================================
    # DEFINITION MANAGEMENT (CRUD + Event Sourced)
    # =========================================================
    
    async def create_definition(
        self,
        org_id: UUID,
        name: str,
        soft_limit_minutes: int,
        hard_limit_minutes: int,
        actor_id: UUID,
        priority: SLAPriority = SLAPriority.P3,
        description: Optional[str] = None,
        business_hours_only: bool = False,
        business_hours_config: Optional[Dict[str, Any]] = None,
        excluded_states: Optional[List[str]] = None,
        escalation_config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SLADefinition:
        """
        Create a new SLA definition.
        
        SLA definitions are templates that can be attached to workflows.
        They define the rules - time limits, business hours, escalations.
        """
        definition_id = uuid4()
        now = datetime.utcnow()
        
        # Build config objects if provided
        bh_config = None
        if business_hours_config:
            bh_config = BusinessHoursConfig(**business_hours_config)
        
        esc_config = None
        if escalation_config:
            esc_config = EscalationConfig(**escalation_config)
        
        # Create the definition
        definition = SLADefinition(
            id=definition_id,
            org_id=org_id,
            name=name,
            description=description,
            soft_limit_minutes=soft_limit_minutes,
            hard_limit_minutes=hard_limit_minutes,
            priority=priority,
            business_hours_only=business_hours_only,
            business_hours_config=bh_config,
            excluded_states=set(excluded_states) if excluded_states else {"paused", "blocked"},
            escalation_config=esc_config,
            metadata=metadata or {},
            created_at=now,
            created_by=actor_id,
        )
        
        # Persist via event
        event_data = definition.to_dict()
        await event_store.append(
            org_id=org_id,
            stream_id=definition_id,
            stream_type="sla_definition",
            event_type=SLAEventType.DEFINITION_CREATED,
            data=event_data,
            actor_id=actor_id,
            metadata={"action": "create_definition", "name": name}
        )
        
        logger.info(f"SLA definition created: {definition_id} ({name})")
        return definition
    
    async def create_definition_from_template(
        self,
        org_id: UUID,
        template_name: str,
        actor_id: UUID,
        name_override: Optional[str] = None,
        **overrides
    ) -> SLADefinition:
        """
        Create definition from predefined template (P1-P4).
        
        Templates provide sensible defaults for common incident priorities.
        """
        if template_name not in DEFAULT_SLA_TEMPLATES:
            raise ValueError(f"Unknown template: {template_name}. Available: {list(DEFAULT_SLA_TEMPLATES.keys())}")
        
        template = DEFAULT_SLA_TEMPLATES[template_name]
        
        # Apply overrides
        soft_limit = overrides.get("soft_limit_minutes", template["soft_limit_minutes"])
        hard_limit = overrides.get("hard_limit_minutes", template["hard_limit_minutes"])
        
        return await self.create_definition(
            org_id=org_id,
            name=name_override or template["name"],
            soft_limit_minutes=soft_limit,
            hard_limit_minutes=hard_limit,
            actor_id=actor_id,
            priority=SLAPriority(template["priority"]),
            description=template.get("description"),
            business_hours_only=overrides.get("business_hours_only", template.get("business_hours_only", False)),
            metadata={"source_template": template_name}
        )
    
    async def get_definition(
        self,
        org_id: UUID,
        definition_id: UUID
    ) -> Optional[SLADefinition]:
        """
        Get SLA definition by replaying events.
        """
        events = await event_store.get_stream(
            org_id=org_id,
            stream_id=definition_id,
            stream_type="sla_definition"
        )
        
        if not events:
            return None
        
        return self._rebuild_definition(events)
    
    async def list_definitions(
        self,
        org_id: UUID,
        include_archived: bool = False
    ) -> List[SLADefinition]:
        """
        List all SLA definitions for an org.
        """
        async with get_db_connection() as conn:
            query = """
                SELECT DISTINCT stream_id
                FROM events
                WHERE org_id = $1 AND stream_type = 'sla_definition'
            """
            rows = await conn.fetch(query, org_id)
        
        definitions = []
        for row in rows:
            defn = await self.get_definition(org_id, row["stream_id"])
            if defn and (include_archived or not defn.is_archived):
                definitions.append(defn)
        
        return definitions
    
    def _rebuild_definition(self, events: List[Dict]) -> Optional[SLADefinition]:
        """Rebuild definition state from events"""
        definition = None
        
        for event in events:
            event_type = event["event_type"]
            data = event["data"]
            
            if event_type == SLAEventType.DEFINITION_CREATED:
                # Handle enum conversion
                priority = SLAPriority(data.get("priority", "p3"))
                
                # Handle business hours config
                bh_config = None
                if data.get("business_hours_config"):
                    bh_config = BusinessHoursConfig(**data["business_hours_config"])
                
                # Handle escalation config
                esc_config = None
                if data.get("escalation_config"):
                    esc_config = EscalationConfig(**data["escalation_config"])
                
                definition = SLADefinition(
                    id=UUID(data["id"]),
                    org_id=UUID(data["org_id"]),
                    name=data["name"],
                    description=data.get("description"),
                    soft_limit_minutes=data["soft_limit_minutes"],
                    hard_limit_minutes=data["hard_limit_minutes"],
                    priority=priority,
                    business_hours_only=data.get("business_hours_only", False),
                    business_hours_config=bh_config,
                    excluded_states=set(data.get("excluded_states", ["paused", "blocked"])),
                    escalation_config=esc_config,
                    metadata=data.get("metadata", {}),
                    created_at=datetime.fromisoformat(data["created_at"]),
                    created_by=UUID(data["created_by"]),
                )
            
            elif event_type == SLAEventType.DEFINITION_UPDATED:
                if definition:
                    for key, value in data.items():
                        if hasattr(definition, key) and key not in ("id", "org_id", "created_at", "created_by"):
                            setattr(definition, key, value)
            
            elif event_type == SLAEventType.DEFINITION_ARCHIVED:
                if definition:
                    definition.is_archived = True
        
        return definition
    
    # =========================================================
    # INSTANCE MANAGEMENT (Lifecycle Events)
    # =========================================================
    
    async def create_instance(
        self,
        org_id: UUID,
        definition_id: UUID,
        workflow_id: UUID,
        actor_id: UUID,
        auto_start: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SLAInstance:
        """
        Create an SLA instance attached to a workflow.
        
        If auto_start=True, the SLA timer starts immediately.
        """
        # Get definition
        definition = await self.get_definition(org_id, definition_id)
        if not definition:
            raise ValueError(f"SLA definition not found: {definition_id}")
        
        instance_id = uuid4()
        now = datetime.utcnow()
        
        # Calculate deadlines
        soft_deadline, hard_deadline = self.engine.calculate_deadlines(
            started_at=now if auto_start else datetime.max,
            soft_limit_minutes=definition.soft_limit_minutes,
            hard_limit_minutes=definition.hard_limit_minutes,
            business_hours_config=definition.business_hours_config if definition.business_hours_only else None
        )
        
        instance = SLAInstance(
            id=instance_id,
            org_id=org_id,
            definition_id=definition_id,
            workflow_id=workflow_id,
            status=SLAStatus.ACTIVE if auto_start else SLAStatus.PENDING,
            started_at=now if auto_start else None,
            soft_deadline=soft_deadline if auto_start else None,
            hard_deadline=hard_deadline if auto_start else None,
            metadata=metadata or {},
            created_at=now,
        )
        
        # Persist creation event
        await event_store.append(
            org_id=org_id,
            stream_id=instance_id,
            stream_type="sla_instance",
            event_type=SLAEventType.INSTANCE_CREATED,
            data=instance.to_dict(),
            actor_id=actor_id,
            metadata={
                "workflow_id": str(workflow_id),
                "definition_id": str(definition_id),
                "auto_start": auto_start
            }
        )
        
        # If auto-started, also emit start event
        if auto_start:
            await event_store.append(
                org_id=org_id,
                stream_id=instance_id,
                stream_type="sla_instance",
                event_type=SLAEventType.INSTANCE_STARTED,
                data={
                    "started_at": now.isoformat(),
                    "soft_deadline": soft_deadline.isoformat(),
                    "hard_deadline": hard_deadline.isoformat()
                },
                actor_id=actor_id,
                metadata={"trigger": "auto_start"}
            )
        
        logger.info(f"SLA instance created: {instance_id} for workflow {workflow_id}")
        return instance
    
    async def start_sla(
        self,
        org_id: UUID,
        instance_id: UUID,
        actor_id: UUID
    ) -> SLAInstance:
        """
        Start the SLA timer (if not auto-started).
        """
        instance = await self.get_instance(org_id, instance_id)
        if not instance:
            raise ValueError(f"SLA instance not found: {instance_id}")
        
        if instance.status != SLAStatus.PENDING:
            raise ValueError(f"Cannot start SLA in status {instance.status}")
        
        definition = await self.get_definition(org_id, instance.definition_id)
        if not definition:
            raise ValueError(f"SLA definition not found: {instance.definition_id}")
        
        now = datetime.utcnow()
        
        # Calculate deadlines
        soft_deadline, hard_deadline = self.engine.calculate_deadlines(
            started_at=now,
            soft_limit_minutes=definition.soft_limit_minutes,
            hard_limit_minutes=definition.hard_limit_minutes,
            business_hours_config=definition.business_hours_config if definition.business_hours_only else None
        )
        
        # Emit start event
        await event_store.append(
            org_id=org_id,
            stream_id=instance_id,
            stream_type="sla_instance",
            event_type=SLAEventType.INSTANCE_STARTED,
            data={
                "started_at": now.isoformat(),
                "soft_deadline": soft_deadline.isoformat(),
                "hard_deadline": hard_deadline.isoformat()
            },
            actor_id=actor_id,
            metadata={"trigger": "manual_start"}
        )
        
        # Return updated instance
        return await self.get_instance(org_id, instance_id)
    
    async def pause_sla(
        self,
        org_id: UUID,
        instance_id: UUID,
        reason: str,
        actor_id: UUID
    ) -> SLAInstance:
        """
        Pause SLA timer.
        
        Time while paused does not count toward SLA.
        Useful for "waiting on customer" states.
        """
        instance = await self.get_instance(org_id, instance_id)
        if not instance:
            raise ValueError(f"SLA instance not found: {instance_id}")
        
        if instance.status != SLAStatus.ACTIVE:
            raise ValueError(f"Cannot pause SLA in status {instance.status}")
        
        if instance.is_paused:
            raise ValueError("SLA is already paused")
        
        now = datetime.utcnow()
        
        await event_store.append(
            org_id=org_id,
            stream_id=instance_id,
            stream_type="sla_instance",
            event_type=SLAEventType.INSTANCE_PAUSED,
            data={
                "paused_at": now.isoformat(),
                "reason": reason,
                "elapsed_before_pause": instance.elapsed_seconds()
            },
            actor_id=actor_id,
            metadata={"reason": reason}
        )
        
        logger.info(f"SLA {instance_id} paused: {reason}")
        return await self.get_instance(org_id, instance_id)
    
    async def resume_sla(
        self,
        org_id: UUID,
        instance_id: UUID,
        actor_id: UUID
    ) -> SLAInstance:
        """
        Resume a paused SLA timer.
        """
        instance = await self.get_instance(org_id, instance_id)
        if not instance:
            raise ValueError(f"SLA instance not found: {instance_id}")
        
        if not instance.is_paused:
            raise ValueError("SLA is not paused")
        
        now = datetime.utcnow()
        pause_duration = self.engine.calculate_pause_duration(
            instance.paused_at, now
        )
        
        await event_store.append(
            org_id=org_id,
            stream_id=instance_id,
            stream_type="sla_instance",
            event_type=SLAEventType.INSTANCE_RESUMED,
            data={
                "resumed_at": now.isoformat(),
                "pause_duration_seconds": pause_duration
            },
            actor_id=actor_id,
            metadata={"pause_duration_minutes": round(pause_duration / 60, 2)}
        )
        
        logger.info(f"SLA {instance_id} resumed after {pause_duration}s pause")
        return await self.get_instance(org_id, instance_id)
    
    async def complete_sla(
        self,
        org_id: UUID,
        instance_id: UUID,
        actor_id: UUID,
        resolution: Optional[str] = None
    ) -> SLAInstance:
        """
        Complete the SLA (workflow finished).
        
        Determines final status: MET or BREACHED based on elapsed time.
        """
        instance = await self.get_instance(org_id, instance_id)
        if not instance:
            raise ValueError(f"SLA instance not found: {instance_id}")
        
        if instance.is_terminal():
            raise ValueError(f"SLA is already terminal: {instance.status}")
        
        definition = await self.get_definition(org_id, instance.definition_id)
        if not definition:
            raise ValueError(f"Definition not found: {instance.definition_id}")
        
        # Check final breach status
        breach_result = self.engine.check_instance_breach(instance, definition)
        now = datetime.utcnow()
        
        # Determine final status
        if breach_result.is_hard_breached:
            final_status = SLAStatus.HARD_BREACH
        elif breach_result.is_soft_breached:
            final_status = SLAStatus.SOFT_BREACH
        else:
            final_status = SLAStatus.MET
        
        await event_store.append(
            org_id=org_id,
            stream_id=instance_id,
            stream_type="sla_instance",
            event_type=SLAEventType.INSTANCE_COMPLETED,
            data={
                "completed_at": now.isoformat(),
                "final_status": final_status.value,
                "total_elapsed_seconds": instance.elapsed_seconds(),
                "total_paused_seconds": instance.total_paused_seconds,
                "breach_result": breach_result.to_dict(),
                "resolution": resolution
            },
            actor_id=actor_id,
            metadata={
                "final_status": final_status.value,
                "elapsed_minutes": round(instance.elapsed_minutes(), 2)
            }
        )
        
        logger.info(f"SLA {instance_id} completed: {final_status.value}")
        return await self.get_instance(org_id, instance_id)
    
    async def cancel_sla(
        self,
        org_id: UUID,
        instance_id: UUID,
        reason: str,
        actor_id: UUID
    ) -> SLAInstance:
        """
        Cancel an SLA (workflow cancelled, no longer relevant).
        """
        instance = await self.get_instance(org_id, instance_id)
        if not instance:
            raise ValueError(f"SLA instance not found: {instance_id}")
        
        if instance.is_terminal():
            raise ValueError(f"SLA is already terminal: {instance.status}")
        
        now = datetime.utcnow()
        
        await event_store.append(
            org_id=org_id,
            stream_id=instance_id,
            stream_type="sla_instance",
            event_type=SLAEventType.INSTANCE_CANCELLED,
            data={
                "cancelled_at": now.isoformat(),
                "reason": reason,
                "elapsed_at_cancellation_seconds": instance.elapsed_seconds()
            },
            actor_id=actor_id,
            metadata={"reason": reason}
        )
        
        logger.info(f"SLA {instance_id} cancelled: {reason}")
        return await self.get_instance(org_id, instance_id)
    
    # =========================================================
    # BREACH DETECTION
    # =========================================================
    
    async def check_breach(
        self,
        org_id: UUID,
        instance_id: UUID
    ) -> BreachCheckResult:
        """
        Check if an SLA instance has breached.
        """
        instance = await self.get_instance(org_id, instance_id)
        if not instance:
            raise ValueError(f"SLA instance not found: {instance_id}")
        
        definition = await self.get_definition(org_id, instance.definition_id)
        if not definition:
            raise ValueError(f"Definition not found: {instance.definition_id}")
        
        return self.engine.check_instance_breach(instance, definition)
    
    async def check_and_record_breach(
        self,
        org_id: UUID,
        instance_id: UUID,
        actor_id: UUID
    ) -> Tuple[BreachCheckResult, bool]:
        """
        Check for breach and emit events if newly breached.
        
        Returns (result, is_newly_breached)
        """
        instance = await self.get_instance(org_id, instance_id)
        if not instance:
            raise ValueError(f"SLA instance not found: {instance_id}")
        
        # Skip if already in terminal state
        if instance.is_terminal():
            return self.engine.check_instance_breach(
                instance,
                await self.get_definition(org_id, instance.definition_id)
            ), False
        
        definition = await self.get_definition(org_id, instance.definition_id)
        result = self.engine.check_instance_breach(instance, definition)
        
        now = datetime.utcnow()
        newly_breached = False
        
        # Check for new hard breach
        if result.is_hard_breached and instance.status != SLAStatus.HARD_BREACH:
            await event_store.append(
                org_id=org_id,
                stream_id=instance_id,
                stream_type="sla_instance",
                event_type=SLAEventType.HARD_BREACH_DETECTED,
                data={
                    "detected_at": now.isoformat(),
                    "exceeded_by_minutes": result.hard_exceeded_by_minutes,
                    "elapsed_minutes": result.elapsed_minutes
                },
                actor_id=actor_id,
                metadata={"severity": "hard"}
            )
            newly_breached = True
            logger.warning(f"HARD BREACH detected: SLA {instance_id}")
        
        # Check for new soft breach
        elif result.is_soft_breached and instance.status not in (SLAStatus.SOFT_BREACH, SLAStatus.HARD_BREACH):
            await event_store.append(
                org_id=org_id,
                stream_id=instance_id,
                stream_type="sla_instance",
                event_type=SLAEventType.SOFT_BREACH_DETECTED,
                data={
                    "detected_at": now.isoformat(),
                    "exceeded_by_minutes": result.soft_exceeded_by_minutes,
                    "elapsed_minutes": result.elapsed_minutes,
                    "time_to_hard_minutes": result.time_to_hard_minutes
                },
                actor_id=actor_id,
                metadata={"severity": "soft"}
            )
            newly_breached = True
            logger.warning(f"SOFT BREACH detected: SLA {instance_id}")
        
        return result, newly_breached
    
    async def predict_breach(
        self,
        org_id: UUID,
        instance_id: UUID
    ) -> BreachPrediction:
        """
        Predict likelihood of SLA breach.
        """
        instance = await self.get_instance(org_id, instance_id)
        if not instance:
            raise ValueError(f"SLA instance not found: {instance_id}")
        
        definition = await self.get_definition(org_id, instance.definition_id)
        if not definition:
            raise ValueError(f"Definition not found: {instance.definition_id}")
        
        if not instance.started_at:
            # SLA hasn't started
            return BreachPrediction(
                will_breach=False,
                probability=0.0,
                predicted_breach_at=None,
                time_remaining_seconds=definition.hard_limit_minutes * 60,
                risk_level="minimal",
                recommendations=["SLA not yet started"],
            )
        
        timer = SLATimer(
            started_at=instance.started_at,
            paused_at=instance.paused_at,
            total_paused_seconds=instance.total_paused_seconds,
            business_hours_config=definition.business_hours_config if definition.business_hours_only else None,
        )
        
        return self.engine.predict_breach(
            timer,
            definition.soft_limit_minutes,
            definition.hard_limit_minutes
        )
    
    # =========================================================
    # INSTANCE RETRIEVAL
    # =========================================================
    
    async def get_instance(
        self,
        org_id: UUID,
        instance_id: UUID
    ) -> Optional[SLAInstance]:
        """
        Get SLA instance by replaying events.
        """
        events = await event_store.get_stream(
            org_id=org_id,
            stream_id=instance_id,
            stream_type="sla_instance"
        )
        
        if not events:
            return None
        
        return self._rebuild_instance(events)
    
    async def get_instances_for_workflow(
        self,
        org_id: UUID,
        workflow_id: UUID
    ) -> List[SLAInstance]:
        """
        Get all SLA instances for a workflow.
        """
        async with get_db_connection() as conn:
            query = """
                SELECT DISTINCT stream_id
                FROM events
                WHERE org_id = $1 
                  AND stream_type = 'sla_instance'
                  AND metadata->>'workflow_id' = $2
            """
            rows = await conn.fetch(query, org_id, str(workflow_id))
        
        instances = []
        for row in rows:
            instance = await self.get_instance(org_id, row["stream_id"])
            if instance:
                instances.append(instance)
        
        return instances
    
    async def list_active_instances(
        self,
        org_id: UUID,
        limit: int = 100
    ) -> List[SLAInstance]:
        """
        List active SLA instances (for monitoring dashboard).
        """
        async with get_db_connection() as conn:
            query = """
                SELECT DISTINCT stream_id
                FROM events
                WHERE org_id = $1 AND stream_type = 'sla_instance'
                ORDER BY stream_id
                LIMIT $2
            """
            rows = await conn.fetch(query, org_id, limit)
        
        instances = []
        for row in rows:
            instance = await self.get_instance(org_id, row["stream_id"])
            if instance and instance.status in (SLAStatus.PENDING, SLAStatus.ACTIVE):
                instances.append(instance)
        
        return instances
    
    def _rebuild_instance(self, events: List[Dict]) -> Optional[SLAInstance]:
        """Rebuild instance state from events"""
        instance = None
        
        for event in events:
            event_type = event["event_type"]
            data = event["data"]
            
            if event_type == SLAEventType.INSTANCE_CREATED:
                instance = SLAInstance(
                    id=UUID(data["id"]),
                    org_id=UUID(data["org_id"]),
                    definition_id=UUID(data["definition_id"]),
                    workflow_id=UUID(data["workflow_id"]),
                    status=SLAStatus(data.get("status", "pending")),
                    started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
                    soft_deadline=datetime.fromisoformat(data["soft_deadline"]) if data.get("soft_deadline") else None,
                    hard_deadline=datetime.fromisoformat(data["hard_deadline"]) if data.get("hard_deadline") else None,
                    metadata=data.get("metadata", {}),
                    created_at=datetime.fromisoformat(data["created_at"]),
                )
            
            elif event_type == SLAEventType.INSTANCE_STARTED:
                if instance:
                    instance.started_at = datetime.fromisoformat(data["started_at"])
                    instance.soft_deadline = datetime.fromisoformat(data["soft_deadline"])
                    instance.hard_deadline = datetime.fromisoformat(data["hard_deadline"])
                    instance.status = SLAStatus.ACTIVE
            
            elif event_type == SLAEventType.INSTANCE_PAUSED:
                if instance:
                    instance.paused_at = datetime.fromisoformat(data["paused_at"])
            
            elif event_type == SLAEventType.INSTANCE_RESUMED:
                if instance:
                    instance.total_paused_seconds += data.get("pause_duration_seconds", 0)
                    instance.paused_at = None
            
            elif event_type == SLAEventType.INSTANCE_COMPLETED:
                if instance:
                    instance.status = SLAStatus(data["final_status"])
                    instance.completed_at = datetime.fromisoformat(data["completed_at"])
            
            elif event_type == SLAEventType.INSTANCE_CANCELLED:
                if instance:
                    instance.status = SLAStatus.CANCELLED
                    instance.completed_at = datetime.fromisoformat(data["cancelled_at"])
            
            elif event_type == SLAEventType.SOFT_BREACH_DETECTED:
                if instance:
                    instance.status = SLAStatus.SOFT_BREACH
            
            elif event_type == SLAEventType.HARD_BREACH_DETECTED:
                if instance:
                    instance.status = SLAStatus.HARD_BREACH
        
        return instance
    
    # =========================================================
    # REPORTING
    # =========================================================
    
    async def get_compliance_report(
        self,
        org_id: UUID,
        from_date: datetime,
        to_date: datetime
    ) -> Dict[str, Any]:
        """
        Generate SLA compliance report for a time period.
        """
        async with get_db_connection() as conn:
            query = """
                SELECT DISTINCT stream_id
                FROM events
                WHERE org_id = $1 
                  AND stream_type = 'sla_instance'
                  AND created_at BETWEEN $2 AND $3
            """
            rows = await conn.fetch(query, org_id, from_date, to_date)
        
        instances = []
        definitions = {}
        
        for row in rows:
            instance = await self.get_instance(org_id, row["stream_id"])
            if instance:
                instances.append(instance)
                if instance.definition_id not in definitions:
                    defn = await self.get_definition(org_id, instance.definition_id)
                    if defn:
                        definitions[instance.definition_id] = defn
        
        # Calculate metrics
        metrics = self.engine.calculate_sla_metrics(instances, definitions)
        
        return {
            "period": {
                "from": from_date.isoformat(),
                "to": to_date.isoformat()
            },
            "metrics": metrics,
            "summary": f"{metrics['compliance_percentage']}% SLA compliance ({metrics['met_count']}/{metrics['met_count'] + metrics['breached_count']})",
            "generated_at": datetime.utcnow().isoformat()
        }


# Singleton instance
sla_service = SLAService()
