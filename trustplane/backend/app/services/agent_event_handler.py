"""
Agent Event Handler

Subscribes to workflow and SLA events to trigger AI agents
at appropriate lifecycle points.

This follows the Event Choreography pattern:
- Events are the source of truth
- Agents react to events (not called directly by workflows)
- Agent decisions are recorded as events
- Humans can review and act on recommendations
"""

from typing import Optional
from uuid import UUID
import logging
import asyncio

from app.models.event import Event, EventType
from app.services.agent_workflow_integration import (
    AgentWorkflowIntegration,
    AgentTriggerPoint,
    get_agent_workflow_integration,
)

logger = logging.getLogger(__name__)


class AgentEventHandler:
    """
    Handles events to trigger AI agents at key lifecycle points.
    
    Event → Agent Pipeline:
    =======================
    
    1. WORKFLOW_CREATED → Triage Agent
       - Classify the request
       - Suggest priority
       - Recommend routing
    
    2. WORKFLOW_TRANSITIONED (to active) → Full Orchestrator
       - SLA risk assessment
       - Workflow analysis
       - Initial recommendations
    
    3. SLA_WARNING → SLA Agent
       - Risk assessment
       - Breach prediction
       - Mitigation recommendations
    
    4. SLA_SOFT_BREACH / SLA_HARD_BREACH → Full Orchestrator
       - Urgent analysis
       - Escalation recommendations
    
    Configuration:
    =============
    Agents can be enabled/disabled per event type via settings.
    """
    
    def __init__(self):
        # Map event types to handlers
        self._handlers = {
            EventType.WORKFLOW_CREATED: self._on_workflow_created,
            EventType.WORKFLOW_TRANSITIONED: self._on_workflow_transitioned,
            EventType.SLA_WARNING: self._on_sla_warning,
            EventType.SLA_SOFT_BREACH: self._on_sla_breach,
            EventType.SLA_HARD_BREACH: self._on_sla_breach,
        }
        
        # Configuration (could be loaded from settings)
        self._config = {
            "enabled": True,
            "auto_triage_on_create": True,
            "auto_analyze_on_start": True,
            "auto_alert_on_sla_warning": True,
            "auto_escalate_on_breach": True,
            "max_concurrent_agents": 5,
        }
        
        # Semaphore to limit concurrent agent runs
        self._semaphore = asyncio.Semaphore(self._config["max_concurrent_agents"])
    
    async def handle_event(self, event: Event) -> None:
        """
        Main entry point for processing events.
        
        Called by the event dispatcher after events are stored.
        Runs asynchronously - doesn't block the main flow.
        """
        if not self._config["enabled"]:
            return
        
        handler = self._handlers.get(event.event_type)
        if handler:
            # Run in background to not block
            asyncio.create_task(self._safe_handle(event, handler))
    
    async def _safe_handle(self, event: Event, handler) -> None:
        """Safely handle event with concurrency limiting and error handling."""
        async with self._semaphore:
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    f"Agent handler error for {event.event_type}: {e}",
                    extra={
                        "event_id": str(event.id),
                        "stream_id": str(event.stream_id),
                        "error": str(e),
                    }
                )
    
    # =========================================================
    # EVENT HANDLERS
    # =========================================================
    
    async def _on_workflow_created(self, event: Event) -> None:
        """
        Handle workflow creation - run triage agent.
        """
        if not self._config["auto_triage_on_create"]:
            return
        
        org_id = event.org_id
        workflow_id = event.stream_id
        
        logger.info(f"Triggering triage agent for new workflow {workflow_id}")
        
        integration = get_agent_workflow_integration(org_id)
        
        try:
            decision = await integration.on_workflow_created(event)
            
            if decision:
                logger.info(
                    f"Triage complete for {workflow_id}: {decision.decision_type.value}",
                    extra={
                        "confidence": decision.confidence.value,
                        "requires_review": decision.requires_human_review,
                    }
                )
        except Exception as e:
            logger.error(f"Triage agent failed: {e}")
    
    async def _on_workflow_transitioned(self, event: Event) -> None:
        """
        Handle workflow state transitions.
        
        Triggers full orchestrator when workflow becomes active.
        """
        if not self._config["auto_analyze_on_start"]:
            return
        
        to_state = event.data.get("to_state")
        from_state = event.data.get("from_state")
        
        # Only run orchestrator when transitioning TO active state
        if to_state != "active":
            return
        
        # Skip if resuming (already analyzed)
        if from_state == "paused":
            return
        
        org_id = event.org_id
        workflow_id = event.stream_id
        
        logger.info(f"Triggering orchestrator for started workflow {workflow_id}")
        
        integration = get_agent_workflow_integration(org_id)
        
        try:
            result = await integration.on_workflow_started(event)
            
            if result:
                final = result.get("final_decision", {})
                logger.info(
                    f"Orchestrator complete for {workflow_id}",
                    extra={
                        "decision_type": final.get("decision_type"),
                        "confidence": final.get("confidence"),
                        "agents_executed": result.get("agents_executed", []),
                    }
                )
        except Exception as e:
            logger.error(f"Orchestrator failed: {e}")
    
    async def _on_sla_warning(self, event: Event) -> None:
        """
        Handle SLA warning - run SLA risk agent.
        """
        if not self._config["auto_alert_on_sla_warning"]:
            return
        
        org_id = event.org_id
        workflow_id = event.data.get("workflow_id")
        sla_instance_id = event.stream_id
        breach_level = event.data.get("breach_level", "warning")
        
        if not workflow_id:
            logger.warning(f"SLA warning event missing workflow_id: {event.id}")
            return
        
        logger.info(
            f"Triggering SLA agent for warning on workflow {workflow_id}",
            extra={"breach_level": breach_level}
        )
        
        integration = get_agent_workflow_integration(org_id)
        
        try:
            decision = await integration.on_sla_warning(
                workflow_id=UUID(workflow_id),
                sla_instance_id=sla_instance_id,
                breach_level=breach_level,
            )
            
            if decision:
                logger.info(
                    f"SLA analysis complete for {workflow_id}",
                    extra={
                        "decision_type": decision.decision_type.value,
                        "is_urgent": decision.is_urgent,
                    }
                )
        except Exception as e:
            logger.error(f"SLA agent failed: {e}")
    
    async def _on_sla_breach(self, event: Event) -> None:
        """
        Handle SLA breach - run full orchestrator with urgent flag.
        """
        if not self._config["auto_escalate_on_breach"]:
            return
        
        org_id = event.org_id
        workflow_id = event.data.get("workflow_id")
        sla_instance_id = event.stream_id
        breach_type = "hard" if event.event_type == EventType.SLA_HARD_BREACH else "soft"
        
        if not workflow_id:
            logger.warning(f"SLA breach event missing workflow_id: {event.id}")
            return
        
        logger.warning(
            f"Triggering orchestrator for SLA {breach_type} breach on workflow {workflow_id}",
            extra={"event_type": event.event_type.value}
        )
        
        integration = get_agent_workflow_integration(org_id)
        
        try:
            result = await integration.on_sla_breach(
                workflow_id=UUID(workflow_id),
                sla_instance_id=sla_instance_id,
            )
            
            if result:
                final = result.get("final_decision", {})
                logger.warning(
                    f"Breach analysis complete for {workflow_id}",
                    extra={
                        "decision_type": final.get("decision_type"),
                        "recommendations": final.get("recommendations", []),
                    }
                )
        except Exception as e:
            logger.error(f"Breach analysis failed: {e}")
    
    # =========================================================
    # CONFIGURATION
    # =========================================================
    
    def configure(self, **kwargs) -> None:
        """Update handler configuration."""
        self._config.update(kwargs)
        
        # Update semaphore if max_concurrent changed
        if "max_concurrent_agents" in kwargs:
            self._semaphore = asyncio.Semaphore(kwargs["max_concurrent_agents"])
    
    def enable(self) -> None:
        """Enable agent event handling."""
        self._config["enabled"] = True
    
    def disable(self) -> None:
        """Disable agent event handling."""
        self._config["enabled"] = False


# Singleton instance
_agent_event_handler: Optional[AgentEventHandler] = None


def get_agent_event_handler() -> AgentEventHandler:
    """Get or create the agent event handler singleton."""
    global _agent_event_handler
    if _agent_event_handler is None:
        _agent_event_handler = AgentEventHandler()
    return _agent_event_handler


def register_agent_handlers(dispatcher) -> None:
    """
    Register agent event handlers with the event dispatcher.
    
    Call this during application startup.
    """
    handler = get_agent_event_handler()
    
    # Register for relevant event types
    dispatcher.subscribe(EventType.WORKFLOW_CREATED, handler.handle_event)
    dispatcher.subscribe(EventType.WORKFLOW_TRANSITIONED, handler.handle_event)
    dispatcher.subscribe(EventType.SLA_WARNING, handler.handle_event)
    dispatcher.subscribe(EventType.SLA_SOFT_BREACH, handler.handle_event)
    dispatcher.subscribe(EventType.SLA_HARD_BREACH, handler.handle_event)
    
    logger.info("Agent event handlers registered")
