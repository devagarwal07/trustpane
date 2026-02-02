"""
SLA-Workflow Coordinator

This module is the GLUE between workflows and SLAs.
It listens to workflow events and triggers appropriate SLA actions.

Design Pattern: Event Choreography
==================================
Instead of workflows directly calling SLA methods (tight coupling),
we use events to coordinate between domains:

    Workflow Domain          SLA Domain
    ===============          ==========
    
    workflow.created ──────► Create SLA instance
    workflow.started ──────► Start SLA timer
    workflow.paused  ──────► Pause SLA timer
    workflow.resumed ──────► Resume SLA timer
    workflow.completed ────► Complete SLA (check if met/breached)
    workflow.failed    ────► Complete SLA (check if met/breached)
    workflow.cancelled ────► Cancel SLA

This decoupling allows:
- Independent testing of each domain
- Easy extension (add new domains without modifying existing)
- Replay capability (re-process events to fix issues)
"""
from typing import Dict, Any, List, Optional, Callable, Awaitable
from uuid import UUID
from datetime import datetime
import logging
import asyncio

from app.models.event import Event, EventType
from app.services.sla_service import sla_service, SLAEventType
from app.services.event_store import event_store
from app.engines.sla_types import SLAStatus

logger = logging.getLogger(__name__)


# Type for event handlers
EventHandler = Callable[[Event], Awaitable[None]]


class SLAWorkflowCoordinator:
    """
    Coordinates SLA lifecycle based on workflow events.
    
    This is an EVENT HANDLER that subscribes to workflow events
    and triggers appropriate SLA actions.
    """
    
    def __init__(self):
        # Map workflow event types to handlers
        self._handlers: Dict[EventType, EventHandler] = {
            EventType.WORKFLOW_CREATED: self._on_workflow_created,
            EventType.WORKFLOW_TRANSITIONED: self._on_workflow_transitioned,
            EventType.WORKFLOW_COMPLETED: self._on_workflow_completed,
            EventType.WORKFLOW_FAILED: self._on_workflow_failed,
        }
        
        # System actor for automated actions
        self._system_actor_id = UUID("00000000-0000-0000-0000-000000000001")
    
    # =========================================================
    # MAIN ENTRY POINT
    # =========================================================
    
    async def handle_event(self, event: Event) -> None:
        """
        Process a workflow event and trigger SLA actions.
        
        Called by the event store after each event is appended.
        """
        handler = self._handlers.get(event.event_type)
        
        if handler:
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    f"SLA coordinator error handling {event.event_type}: {e}",
                    extra={"event_id": str(event.id), "error": str(e)}
                )
                # Don't re-raise - we don't want to fail the original operation
    
    # =========================================================
    # WORKFLOW EVENT HANDLERS
    # =========================================================
    
    async def _on_workflow_created(self, event: Event) -> None:
        """
        When a workflow is created with an SLA definition,
        automatically create and start an SLA instance.
        """
        org_id = event.org_id
        workflow_id = event.stream_id
        sla_definition_id = event.data.get("sla_definition_id")
        
        if not sla_definition_id:
            logger.debug(f"Workflow {workflow_id} created without SLA")
            return
        
        try:
            # Auto-create SLA instance
            instance = await sla_service.create_instance(
                org_id=org_id,
                definition_id=UUID(sla_definition_id),
                workflow_id=workflow_id,
                actor_id=self._system_actor_id,
                auto_start=False,  # Start when workflow starts
                metadata={
                    "auto_created": True,
                    "trigger_event": str(event.id),
                }
            )
            
            logger.info(
                f"SLA instance {instance.id} created for workflow {workflow_id}"
            )
        except Exception as e:
            logger.error(f"Failed to create SLA instance: {e}")
    
    async def _on_workflow_transitioned(self, event: Event) -> None:
        """
        Handle workflow state transitions.
        
        Key transitions:
        - pending → active: Start SLA timer
        - active → paused: Pause SLA timer
        - paused → active: Resume SLA timer
        - * → cancelled: Cancel SLA
        """
        org_id = event.org_id
        workflow_id = event.stream_id
        from_state = event.data.get("from_state")
        to_state = event.data.get("to_state")
        
        # Get SLA instances for this workflow
        instances = await sla_service.get_instances_for_workflow(
            org_id=org_id,
            workflow_id=workflow_id
        )
        
        if not instances:
            return
        
        for instance in instances:
            # Skip terminal instances
            if instance.is_terminal():
                continue
            
            try:
                await self._handle_transition_for_sla(
                    org_id=org_id,
                    instance=instance,
                    from_state=from_state,
                    to_state=to_state,
                    event=event
                )
            except Exception as e:
                logger.error(
                    f"Error handling transition for SLA {instance.id}: {e}"
                )
    
    async def _handle_transition_for_sla(
        self,
        org_id: UUID,
        instance,
        from_state: str,
        to_state: str,
        event: Event
    ) -> None:
        """Handle a specific transition for an SLA instance"""
        
        # PENDING → ACTIVE: Start the SLA timer
        if from_state == "pending" and to_state == "active":
            if instance.status == SLAStatus.PENDING:
                await sla_service.start_sla(
                    org_id=org_id,
                    instance_id=instance.id,
                    actor_id=self._system_actor_id
                )
                logger.info(f"SLA {instance.id} started")
        
        # ACTIVE → PAUSED: Pause the SLA timer
        elif from_state == "active" and to_state == "paused":
            if instance.status == SLAStatus.ACTIVE and not instance.is_paused:
                await sla_service.pause_sla(
                    org_id=org_id,
                    instance_id=instance.id,
                    reason=event.data.get("reason", "Workflow paused"),
                    actor_id=self._system_actor_id
                )
                logger.info(f"SLA {instance.id} paused")
        
        # PAUSED → ACTIVE: Resume the SLA timer
        elif from_state == "paused" and to_state == "active":
            if instance.is_paused:
                await sla_service.resume_sla(
                    org_id=org_id,
                    instance_id=instance.id,
                    actor_id=self._system_actor_id
                )
                logger.info(f"SLA {instance.id} resumed")
        
        # * → CANCELLED: Cancel the SLA
        elif to_state == "cancelled":
            await sla_service.cancel_sla(
                org_id=org_id,
                instance_id=instance.id,
                reason=event.data.get("reason", "Workflow cancelled"),
                actor_id=self._system_actor_id
            )
            logger.info(f"SLA {instance.id} cancelled")
        
        # After any transition, check for breaches
        if instance.status in (SLAStatus.ACTIVE, SLAStatus.PENDING):
            await self._check_for_breaches(org_id, instance.id)
    
    async def _on_workflow_completed(self, event: Event) -> None:
        """
        When a workflow completes, finalize SLA status.
        """
        await self._finalize_sla_for_workflow(
            org_id=event.org_id,
            workflow_id=event.stream_id,
            resolution="Workflow completed successfully"
        )
    
    async def _on_workflow_failed(self, event: Event) -> None:
        """
        When a workflow fails, finalize SLA status.
        """
        reason = event.data.get("reason", "Workflow failed")
        await self._finalize_sla_for_workflow(
            org_id=event.org_id,
            workflow_id=event.stream_id,
            resolution=f"Workflow failed: {reason}"
        )
    
    # =========================================================
    # BREACH DETECTION
    # =========================================================
    
    async def _check_for_breaches(
        self,
        org_id: UUID,
        instance_id: UUID
    ) -> None:
        """
        Check for SLA breaches and emit events if newly breached.
        """
        try:
            result, newly_breached = await sla_service.check_and_record_breach(
                org_id=org_id,
                instance_id=instance_id,
                actor_id=self._system_actor_id
            )
            
            if newly_breached:
                logger.warning(
                    f"SLA breach detected: {instance_id} - {result.status.value}"
                )
        except Exception as e:
            logger.error(f"Error checking breach for SLA {instance_id}: {e}")
    
    async def check_all_active_slas(self, org_id: UUID) -> Dict[str, Any]:
        """
        Batch check all active SLAs for breaches.
        
        Called periodically by a background job to catch breaches
        even if no workflow events occur.
        
        Returns summary of findings.
        """
        instances = await sla_service.list_active_instances(org_id)
        
        results = {
            "checked": 0,
            "new_soft_breaches": 0,
            "new_hard_breaches": 0,
            "at_risk": [],
        }
        
        for instance in instances:
            results["checked"] += 1
            
            try:
                # Check for breach
                check_result, newly_breached = await sla_service.check_and_record_breach(
                    org_id=org_id,
                    instance_id=instance.id,
                    actor_id=self._system_actor_id
                )
                
                if newly_breached:
                    if check_result.is_hard_breached:
                        results["new_hard_breaches"] += 1
                    elif check_result.is_soft_breached:
                        results["new_soft_breaches"] += 1
                
                # Check for at-risk SLAs (>75% time consumed)
                prediction = await sla_service.predict_breach(org_id, instance.id)
                if prediction.risk_level in ("high", "critical") and not check_result.is_hard_breached:
                    results["at_risk"].append({
                        "instance_id": str(instance.id),
                        "workflow_id": str(instance.workflow_id),
                        "risk_level": prediction.risk_level,
                        "probability": prediction.probability,
                        "time_remaining_minutes": round(prediction.time_remaining_seconds / 60, 2),
                    })
            
            except Exception as e:
                logger.error(f"Error checking SLA {instance.id}: {e}")
        
        return results
    
    # =========================================================
    # FINALIZATION
    # =========================================================
    
    async def _finalize_sla_for_workflow(
        self,
        org_id: UUID,
        workflow_id: UUID,
        resolution: str
    ) -> None:
        """
        Finalize all SLA instances for a workflow.
        """
        instances = await sla_service.get_instances_for_workflow(
            org_id=org_id,
            workflow_id=workflow_id
        )
        
        for instance in instances:
            if not instance.is_terminal():
                try:
                    await sla_service.complete_sla(
                        org_id=org_id,
                        instance_id=instance.id,
                        actor_id=self._system_actor_id,
                        resolution=resolution
                    )
                    logger.info(f"SLA {instance.id} finalized")
                except Exception as e:
                    logger.error(f"Error finalizing SLA {instance.id}: {e}")


# Singleton instance
sla_workflow_coordinator = SLAWorkflowCoordinator()


# =========================================================
# BACKGROUND JOB: Periodic Breach Checker
# =========================================================

class SLABreachChecker:
    """
    Background job that periodically checks for SLA breaches.
    
    This catches breaches even when no workflow events occur.
    For example, a workflow that's been idle for hours.
    """
    
    def __init__(self, check_interval_seconds: int = 60):
        self.check_interval = check_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self, org_ids: List[UUID]) -> None:
        """Start the background checker"""
        self._running = True
        self._task = asyncio.create_task(self._run(org_ids))
        logger.info("SLA breach checker started")
    
    async def stop(self) -> None:
        """Stop the background checker"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SLA breach checker stopped")
    
    async def _run(self, org_ids: List[UUID]) -> None:
        """Main loop"""
        while self._running:
            try:
                for org_id in org_ids:
                    results = await sla_workflow_coordinator.check_all_active_slas(org_id)
                    
                    if results["new_soft_breaches"] or results["new_hard_breaches"]:
                        logger.warning(
                            f"Org {org_id}: {results['new_soft_breaches']} soft breaches, "
                            f"{results['new_hard_breaches']} hard breaches detected"
                        )
                
                await asyncio.sleep(self.check_interval)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in breach checker: {e}")
                await asyncio.sleep(self.check_interval)


# Singleton breach checker
breach_checker = SLABreachChecker()
