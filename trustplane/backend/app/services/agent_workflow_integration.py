"""
Agent-Workflow Integration Service

This module bridges AI agents with the workflow system.
It provides the glue that:
1. Enriches agent context with workflow/SLA/policy data
2. Processes agent decisions and emits events
3. Triggers agents at key workflow lifecycle points
4. Maintains strict read-only for agents (decisions only)

Key Design Principles:
======================
- Agents NEVER mutate data directly
- Agent decisions are EVENTS in the ledger
- Humans can review/override agent recommendations
- Full audit trail of agent involvement
"""

from typing import Any, Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
import logging
import asyncio

from app.models.event import Event, EventCreate, EventType
from app.services.event_store import event_store
from app.services.workflow_service import WorkflowService, WorkflowSnapshot, workflow_service
from app.services.sla_service import sla_service
from app.services.policy_service import PolicyService
from app.services.event_dispatcher import get_event_dispatcher
from app.agents import (
    AgentContext, AgentDecision, AgentType, DecisionType, DecisionConfidence,
    create_sla_agent, create_workflow_agent, create_triage_agent,
    get_orchestrator,
)

logger = logging.getLogger(__name__)


class AgentTriggerPoint(str, Enum):
    """Points in workflow lifecycle where agents can be triggered."""
    WORKFLOW_CREATED = "workflow_created"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_TRANSITIONED = "workflow_transitioned"
    SLA_WARNING = "sla_warning"
    SLA_BREACH = "sla_breach"
    MANUAL_REQUEST = "manual_request"
    PERIODIC_CHECK = "periodic_check"
    ESCALATION_NEEDED = "escalation_needed"


@dataclass
class AgentWorkflowContext:
    """
    Rich context combining workflow, SLA, and policy data for agents.
    """
    org_id: UUID
    workflow_id: UUID
    
    # Workflow snapshot
    workflow: Optional[WorkflowSnapshot] = None
    
    # SLA data
    sla_instance: Optional[dict] = None
    sla_definition: Optional[dict] = None
    
    # Policy context
    applicable_policies: list[dict] = field(default_factory=list)
    
    # Event history
    recent_events: list[dict] = field(default_factory=list)
    
    # Related workflows (for pattern matching)
    similar_workflows: list[dict] = field(default_factory=list)
    
    # Trigger information
    trigger_point: Optional[AgentTriggerPoint] = None
    trigger_event: Optional[Event] = None
    
    # Metadata
    customer_tier: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    
    def to_agent_context(self, user_id: Optional[str] = None) -> AgentContext:
        """Convert to AgentContext for agent consumption."""
        sla_deadline = None
        sla_remaining = None
        sla_breach_level = None
        sla_is_paused = None
        
        if self.sla_instance:
            if self.sla_instance.get("deadline"):
                deadline_str = self.sla_instance["deadline"]
                if isinstance(deadline_str, str):
                    sla_deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
                else:
                    sla_deadline = deadline_str
            sla_remaining = self.sla_instance.get("time_remaining_seconds")
            sla_breach_level = self.sla_instance.get("breach_level")
            sla_is_paused = self.sla_instance.get("is_paused")
        
        workflow_created_at = None
        if self.workflow and self.workflow.created_at:
            workflow_created_at = self.workflow.created_at
        
        return AgentContext(
            org_id=self.org_id,
            workflow_id=self.workflow_id,
            sla_id=UUID(self.sla_instance["id"]) if self.sla_instance else None,
            workflow_state=self.workflow.current_state.value if self.workflow else None,
            workflow_priority=self.workflow.config.get("priority") if self.workflow else None,
            workflow_created_at=workflow_created_at,
            workflow_owner_id=str(self.workflow.assignee_id) if self.workflow and self.workflow.assignee_id else None,
            sla_deadline=sla_deadline,
            sla_time_remaining_seconds=sla_remaining,
            sla_breach_level=sla_breach_level,
            sla_is_paused=sla_is_paused,
            event_history=self.recent_events,
            similar_workflows=[w.to_dict() if hasattr(w, 'to_dict') else w for w in self.similar_workflows],
            user_id=user_id,
            metadata={
                "customer_tier": self.customer_tier,
                "tags": self.tags,
                "trigger_point": self.trigger_point.value if self.trigger_point else None,
                "workflow_name": self.workflow.name if self.workflow else None,
                "workflow_type": self.workflow.workflow_type.value if self.workflow else None,
                "sla_definition_name": self.sla_definition.get("name") if self.sla_definition else None,
                "policy_count": len(self.applicable_policies),
            }
        )


class AgentWorkflowIntegration:
    """
    Main integration layer between agents and workflows.
    
    This service:
    1. Gathers context for agents from multiple sources
    2. Triggers agents at appropriate lifecycle points
    3. Records agent decisions as events
    4. Provides hooks for human review of agent recommendations
    """
    
    def __init__(self, org_id: UUID):
        self.org_id = org_id
        self.workflow_service = workflow_service
        self.sla_service = sla_service
        self.dispatcher = get_event_dispatcher()
        
        # Agent system ID for audit trail
        self._agent_system_id = UUID("00000000-0000-0000-0000-000000000002")
    
    # =========================================================
    # CONTEXT BUILDING
    # =========================================================
    
    async def build_context(
        self,
        workflow_id: UUID,
        trigger_point: Optional[AgentTriggerPoint] = None,
        trigger_event: Optional[Event] = None,
        include_history: bool = True,
        include_similar: bool = False,
        history_limit: int = 50,
    ) -> AgentWorkflowContext:
        """
        Build rich context for agents by gathering data from all sources.
        
        This is READ-ONLY - no mutations.
        """
        context = AgentWorkflowContext(
            org_id=self.org_id,
            workflow_id=workflow_id,
            trigger_point=trigger_point,
            trigger_event=trigger_event,
        )
        
        # Gather data in parallel for efficiency
        tasks = [
            self._load_workflow(workflow_id),
            self._load_sla(workflow_id),
            self._load_policies(workflow_id),
        ]
        
        if include_history:
            tasks.append(self._load_event_history(workflow_id, limit=history_limit))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        context.workflow = results[0] if not isinstance(results[0], Exception) else None
        
        sla_data = results[1] if not isinstance(results[1], Exception) else None
        if sla_data:
            context.sla_instance = sla_data.get("instance")
            context.sla_definition = sla_data.get("definition")
        
        context.applicable_policies = results[2] if not isinstance(results[2], Exception) else []
        
        if include_history and len(results) > 3:
            context.recent_events = results[3] if not isinstance(results[3], Exception) else []
        
        # Load similar workflows if requested (expensive operation)
        if include_similar:
            context.similar_workflows = await self._find_similar_workflows(context)
        
        # Extract customer tier from workflow config
        if context.workflow and context.workflow.config:
            context.customer_tier = context.workflow.config.get("customer_tier")
            context.tags = context.workflow.config.get("tags", [])
        
        return context
    
    async def _load_workflow(self, workflow_id: UUID) -> Optional[WorkflowSnapshot]:
        """Load workflow snapshot."""
        try:
            return await self.workflow_service.get_workflow(self.org_id, workflow_id)
        except Exception as e:
            logger.warning(f"Failed to load workflow {workflow_id}: {e}")
            return None
    
    async def _load_sla(self, workflow_id: UUID) -> Optional[dict]:
        """Load SLA instance and definition."""
        try:
            instances = await self.sla_service.get_instances_for_workflow(
                org_id=self.org_id,
                workflow_id=workflow_id
            )
            
            if not instances:
                return None
            
            instance = instances[0]
            definition = await self.sla_service.get_definition(
                self.org_id,
                instance.definition_id
            )
            
            return {
                "instance": instance.to_dict() if hasattr(instance, 'to_dict') else instance.__dict__,
                "definition": definition.to_dict() if definition and hasattr(definition, 'to_dict') else (definition.__dict__ if definition else None),
            }
        except Exception as e:
            logger.warning(f"Failed to load SLA for workflow {workflow_id}: {e}")
            return None
    
    async def _load_policies(self, workflow_id: UUID) -> list[dict]:
        """Load applicable policies for this workflow."""
        try:
            policy_service = PolicyService(self.org_id)
            await policy_service.initialize()
            
            # Get workflow to determine applicable policies
            workflow = await self._load_workflow(workflow_id)
            if not workflow:
                return []
            
            # Get policies that might apply to this workflow type
            policies = policy_service.engine.policies
            applicable = []
            
            for policy in policies:
                # Filter policies relevant to workflow operations
                if "workflow" in policy.resources or "*" in policy.resources:
                    applicable.append({
                        "id": policy.id,
                        "name": policy.name,
                        "effect": policy.effect.value,
                        "actions": policy.actions,
                        "conditions": policy.conditions,
                    })
            
            return applicable
        except Exception as e:
            logger.warning(f"Failed to load policies: {e}")
            return []
    
    async def _load_event_history(self, workflow_id: UUID, limit: int = 50) -> list[dict]:
        """Load recent events for this workflow."""
        try:
            events = await event_store.get_stream_events(
                org_id=self.org_id,
                stream_id=workflow_id,
                limit=limit
            )
            
            return [
                {
                    "id": str(e.id),
                    "event_type": e.event_type.value,
                    "data": e.data,
                    "timestamp": e.timestamp.isoformat(),
                    "actor_id": str(e.actor_id) if e.actor_id else None,
                    "actor_type": e.actor_type,
                }
                for e in events
            ]
        except Exception as e:
            logger.warning(f"Failed to load event history: {e}")
            return []
    
    async def _find_similar_workflows(
        self,
        context: AgentWorkflowContext,
        limit: int = 5
    ) -> list[dict]:
        """
        Find similar workflows for pattern matching.
        
        Similarity based on:
        - Same workflow type
        - Similar customer tier
        - Completed workflows (for learning)
        """
        if not context.workflow:
            return []
        
        try:
            # Query for similar completed workflows
            similar = await self.workflow_service.find_workflows(
                org_id=self.org_id,
                workflow_type=context.workflow.workflow_type,
                states=["completed", "failed"],
                limit=limit,
                exclude_id=context.workflow_id,
            )
            
            return [w.to_dict() for w in similar] if similar else []
        except Exception as e:
            logger.warning(f"Failed to find similar workflows: {e}")
            return []
    
    # =========================================================
    # AGENT EXECUTION
    # =========================================================
    
    async def run_agent(
        self,
        workflow_id: UUID,
        agent_type: AgentType,
        trigger_point: AgentTriggerPoint = AgentTriggerPoint.MANUAL_REQUEST,
        user_id: Optional[str] = None,
        record_decision: bool = True,
    ) -> AgentDecision:
        """
        Run a specific agent for a workflow.
        
        Returns the agent's decision (recommendation only).
        If record_decision=True, emits an AGENT_DECISION event.
        """
        # Build context
        context = await self.build_context(
            workflow_id=workflow_id,
            trigger_point=trigger_point,
            include_history=True,
            include_similar=agent_type == AgentType.WORKFLOW,
        )
        
        agent_context = context.to_agent_context(user_id)
        
        # Create appropriate agent
        agent_map = {
            AgentType.SLA_RISK: create_sla_agent,
            AgentType.WORKFLOW: create_workflow_agent,
            AgentType.TRIAGE: create_triage_agent,
        }
        
        factory = agent_map.get(agent_type)
        if not factory:
            raise ValueError(f"Unsupported agent type: {agent_type}")
        
        agent = factory()
        
        # Run agent
        decision = await agent.run(agent_context)
        
        # Record decision as event
        if record_decision:
            await self._record_decision_event(
                workflow_id=workflow_id,
                decision=decision,
                trigger_point=trigger_point,
            )
        
        return decision
    
    async def run_orchestrator(
        self,
        workflow_id: UUID,
        trigger_point: AgentTriggerPoint = AgentTriggerPoint.MANUAL_REQUEST,
        user_id: Optional[str] = None,
        parallel: bool = True,
        record_decision: bool = True,
    ) -> dict:
        """
        Run the full agent orchestrator for a workflow.
        
        Executes all agents and synthesizes their decisions.
        """
        # Build rich context
        context = await self.build_context(
            workflow_id=workflow_id,
            trigger_point=trigger_point,
            include_history=True,
            include_similar=True,
        )
        
        agent_context = context.to_agent_context(user_id)
        
        # Get orchestrator
        orchestrator = get_orchestrator()
        
        # Run orchestration
        result = await orchestrator.run(self.org_id, agent_context)
        
        # Record synthesized decision
        if record_decision and result.get("final_decision"):
            await self._record_orchestrator_event(
                workflow_id=workflow_id,
                result=result,
                trigger_point=trigger_point,
            )
        
        return result
    
    # =========================================================
    # DECISION RECORDING
    # =========================================================
    
    async def _record_decision_event(
        self,
        workflow_id: UUID,
        decision: AgentDecision,
        trigger_point: AgentTriggerPoint,
    ) -> None:
        """Record an agent decision as an event in the ledger."""
        event = EventCreate(
            stream_id=workflow_id,
            event_type=EventType.AGENT_DECISION,
            data={
                "decision_id": str(decision.id),
                "agent_type": decision.agent_type.value,
                "agent_id": decision.agent_id,
                "decision_type": decision.decision_type.value,
                "confidence": decision.confidence.value,
                "reasoning": decision.reasoning,
                "evidence": decision.evidence,
                "recommendations": decision.recommendations,
                "suggested_action": decision.suggested_action,
                "suggested_assignee": decision.suggested_assignee,
                "requires_human_review": decision.requires_human_review,
                "is_urgent": decision.is_urgent,
                "decision_hash": decision.decision_hash,
                "trigger_point": trigger_point.value,
            },
            metadata={
                "processing_time_ms": decision.processing_time_ms,
            },
            actor_id=self._agent_system_id,
            actor_type="agent",
        )
        
        await event_store.append(self.org_id, event, self._agent_system_id)
        
        logger.info(
            f"Agent decision recorded: {decision.agent_type.value} -> {decision.decision_type.value}",
            extra={
                "workflow_id": str(workflow_id),
                "decision_id": str(decision.id),
                "confidence": decision.confidence.value,
            }
        )
    
    async def _record_orchestrator_event(
        self,
        workflow_id: UUID,
        result: dict,
        trigger_point: AgentTriggerPoint,
    ) -> None:
        """Record orchestrator result as an event."""
        final = result.get("final_decision", {})
        
        event = EventCreate(
            stream_id=workflow_id,
            event_type=EventType.AGENT_DECISION,
            data={
                "decision_id": result.get("request_id"),
                "agent_type": "orchestrator",
                "agent_id": "orchestrator",
                "decision_type": final.get("decision_type", "recommend"),
                "confidence": final.get("confidence", "medium"),
                "reasoning": final.get("reasoning", ""),
                "recommendations": final.get("recommendations", []),
                "requires_human_review": final.get("requires_human_review", True),
                "is_urgent": final.get("is_urgent", False),
                "trigger_point": trigger_point.value,
                "agents_executed": result.get("agents_executed", []),
                "individual_decisions": {
                    "sla": result.get("agent_decisions", {}).get("sla"),
                    "workflow": result.get("agent_decisions", {}).get("workflow"),
                    "triage": result.get("agent_decisions", {}).get("triage"),
                },
            },
            metadata={
                "execution_time_ms": result.get("execution_time_ms"),
                "errors_count": len(result.get("errors", [])),
            },
            actor_id=self._agent_system_id,
            actor_type="agent",
        )
        
        await event_store.append(self.org_id, event, self._agent_system_id)
    
    # =========================================================
    # LIFECYCLE HOOKS
    # =========================================================
    
    async def on_workflow_created(self, event: Event) -> Optional[AgentDecision]:
        """
        Hook called when a workflow is created.
        
        Runs triage agent to classify and prioritize.
        """
        workflow_id = event.stream_id
        
        return await self.run_agent(
            workflow_id=workflow_id,
            agent_type=AgentType.TRIAGE,
            trigger_point=AgentTriggerPoint.WORKFLOW_CREATED,
        )
    
    async def on_workflow_started(self, event: Event) -> Optional[dict]:
        """
        Hook called when a workflow starts.
        
        Runs orchestrator for initial analysis.
        """
        workflow_id = event.stream_id
        
        return await self.run_orchestrator(
            workflow_id=workflow_id,
            trigger_point=AgentTriggerPoint.WORKFLOW_STARTED,
        )
    
    async def on_sla_warning(
        self,
        workflow_id: UUID,
        sla_instance_id: UUID,
        breach_level: str,
    ) -> Optional[AgentDecision]:
        """
        Hook called when SLA warning threshold is crossed.
        
        Runs SLA agent to assess risk and recommend action.
        """
        return await self.run_agent(
            workflow_id=workflow_id,
            agent_type=AgentType.SLA_RISK,
            trigger_point=AgentTriggerPoint.SLA_WARNING,
        )
    
    async def on_sla_breach(
        self,
        workflow_id: UUID,
        sla_instance_id: UUID,
    ) -> Optional[dict]:
        """
        Hook called when SLA is breached.
        
        Runs full orchestrator with urgent flag.
        """
        return await self.run_orchestrator(
            workflow_id=workflow_id,
            trigger_point=AgentTriggerPoint.SLA_BREACH,
        )
    
    async def on_escalation_needed(
        self,
        workflow_id: UUID,
        reason: str,
    ) -> Optional[dict]:
        """
        Hook called when human escalation is needed.
        
        Runs orchestrator to provide context for human review.
        """
        return await self.run_orchestrator(
            workflow_id=workflow_id,
            trigger_point=AgentTriggerPoint.ESCALATION_NEEDED,
        )
    
    # =========================================================
    # HUMAN REVIEW
    # =========================================================
    
    async def acknowledge_decision(
        self,
        workflow_id: UUID,
        decision_id: UUID,
        user_id: UUID,
        accepted: bool,
        feedback: Optional[str] = None,
    ) -> None:
        """
        Record human acknowledgment/override of an agent decision.
        
        This is critical for:
        - Audit trail (who approved/rejected)
        - Learning (which decisions need adjustment)
        - Accountability (human is responsible for final action)
        """
        event = EventCreate(
            stream_id=workflow_id,
            event_type=EventType.AGENT_DECISION_REVIEWED,
            data={
                "decision_id": str(decision_id),
                "accepted": accepted,
                "feedback": feedback,
                "reviewer_id": str(user_id),
            },
            metadata={
                "review_timestamp": datetime.now(timezone.utc).isoformat(),
            },
            actor_id=user_id,
            actor_type="user",
        )
        
        await event_store.append(self.org_id, event, user_id)
        
        logger.info(
            f"Agent decision {'accepted' if accepted else 'rejected'} by user",
            extra={
                "workflow_id": str(workflow_id),
                "decision_id": str(decision_id),
                "reviewer_id": str(user_id),
            }
        )
    
    async def apply_recommendation(
        self,
        workflow_id: UUID,
        decision_id: UUID,
        user_id: UUID,
        action: str,
        parameters: Optional[dict] = None,
    ) -> dict:
        """
        Apply an agent's recommendation through the workflow system.
        
        The HUMAN initiates the action - agent only recommended it.
        This maintains clear accountability.
        """
        # First acknowledge the decision
        await self.acknowledge_decision(
            workflow_id=workflow_id,
            decision_id=decision_id,
            user_id=user_id,
            accepted=True,
            feedback=f"Applied recommendation: {action}",
        )
        
        # Execute the action based on type
        result = {"action": action, "status": "pending"}
        
        if action == "transition":
            to_state = parameters.get("to_state") if parameters else None
            if to_state:
                from app.services.workflow_service import WorkflowState
                await self.workflow_service.transition(
                    org_id=self.org_id,
                    workflow_id=workflow_id,
                    to_state=WorkflowState(to_state),
                    actor_id=user_id,
                    actor_type="user",
                    reason=f"Following agent recommendation (decision: {decision_id})",
                )
                result["status"] = "completed"
                result["new_state"] = to_state
        
        elif action == "assign":
            assignee_id = parameters.get("assignee_id") if parameters else None
            if assignee_id:
                await self.workflow_service.assign(
                    org_id=self.org_id,
                    workflow_id=workflow_id,
                    assignee_id=UUID(assignee_id),
                    actor_id=user_id,
                )
                result["status"] = "completed"
                result["assignee_id"] = assignee_id
        
        elif action == "escalate":
            # Record escalation event
            event = EventCreate(
                stream_id=workflow_id,
                event_type=EventType.WORKFLOW_ESCALATED,
                data={
                    "reason": parameters.get("reason", "Agent recommended escalation"),
                    "decision_id": str(decision_id),
                    "escalation_level": parameters.get("level", "tier2"),
                },
                actor_id=user_id,
                actor_type="user",
            )
            await event_store.append(self.org_id, event, user_id)
            result["status"] = "completed"
        
        else:
            result["status"] = "unsupported"
            result["message"] = f"Action '{action}' not implemented"
        
        return result


# Factory function
def create_agent_workflow_integration(org_id: UUID) -> AgentWorkflowIntegration:
    """Create an agent-workflow integration instance."""
    return AgentWorkflowIntegration(org_id)


# Singleton per org (cached)
_integrations: dict[UUID, AgentWorkflowIntegration] = {}


def get_agent_workflow_integration(org_id: UUID) -> AgentWorkflowIntegration:
    """Get or create agent-workflow integration for an org."""
    if org_id not in _integrations:
        _integrations[org_id] = create_agent_workflow_integration(org_id)
    return _integrations[org_id]
