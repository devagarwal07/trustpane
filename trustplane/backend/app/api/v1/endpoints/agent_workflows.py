"""
Agent-Workflow Integration API Endpoints

REST API for triggering agents on workflows and processing decisions.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.core.auth import get_current_user, get_current_org_id
from app.core.database import get_supabase
from app.services.agent_workflow_integration import (
    AgentWorkflowIntegration,
    AgentTriggerPoint,
    get_agent_workflow_integration,
)
from app.agents import AgentType, DecisionType


router = APIRouter(prefix="/agent-workflows", tags=["agent-workflows"])


# Request/Response Models

class AgentAnalysisRequest(BaseModel):
    """Request to run agent analysis on a workflow."""
    workflow_id: UUID
    agent_type: Optional[str] = Field(
        None,
        pattern="^(sla_risk|workflow|triage)$",
        description="Specific agent to run, or null for full orchestration"
    )
    include_similar: bool = Field(
        default=False,
        description="Include similar workflows for pattern matching (slower)"
    )


class DecisionReviewRequest(BaseModel):
    """Request to review/acknowledge an agent decision."""
    decision_id: UUID
    accepted: bool
    feedback: Optional[str] = None


class ApplyRecommendationRequest(BaseModel):
    """Request to apply an agent's recommendation."""
    decision_id: UUID
    action: str = Field(..., description="Action to take: transition, assign, escalate")
    parameters: Optional[dict] = Field(
        default=None,
        description="Action parameters (e.g., to_state, assignee_id)"
    )


class WorkflowContextResponse(BaseModel):
    """Response with workflow context for agents."""
    workflow_id: str
    workflow_state: Optional[str]
    workflow_type: Optional[str]
    workflow_name: Optional[str]
    sla_status: Optional[dict]
    policy_count: int
    event_count: int
    customer_tier: Optional[str]


# Endpoints

@router.post("/analyze", response_model=dict)
async def analyze_workflow(
    request: AgentAnalysisRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Run AI agent analysis on a workflow.
    
    If agent_type is specified, runs that specific agent.
    Otherwise, runs the full orchestrator with all agents.
    
    Agent decisions are recorded in the event ledger.
    """
    integration = get_agent_workflow_integration(org_id)
    
    if request.agent_type:
        # Run specific agent
        agent_type_map = {
            "sla_risk": AgentType.SLA_RISK,
            "workflow": AgentType.WORKFLOW,
            "triage": AgentType.TRIAGE,
        }
        
        agent_type = agent_type_map.get(request.agent_type)
        if not agent_type:
            raise HTTPException(status_code=400, detail=f"Unknown agent type: {request.agent_type}")
        
        decision = await integration.run_agent(
            workflow_id=request.workflow_id,
            agent_type=agent_type,
            trigger_point=AgentTriggerPoint.MANUAL_REQUEST,
            user_id=current_user.get("sub"),
        )
        
        return {
            "type": "single_agent",
            "agent_type": decision.agent_type.value,
            "decision": {
                "id": str(decision.id),
                "decision_type": decision.decision_type.value,
                "confidence": decision.confidence.value,
                "reasoning": decision.reasoning,
                "evidence": decision.evidence,
                "recommendations": decision.recommendations,
                "suggested_action": decision.suggested_action,
                "suggested_assignee": decision.suggested_assignee,
                "requires_human_review": decision.requires_human_review,
                "is_urgent": decision.is_urgent,
                "processing_time_ms": decision.processing_time_ms,
            },
            "timestamp": decision.timestamp.isoformat(),
        }
    else:
        # Run full orchestrator
        result = await integration.run_orchestrator(
            workflow_id=request.workflow_id,
            trigger_point=AgentTriggerPoint.MANUAL_REQUEST,
            user_id=current_user.get("sub"),
        )
        
        return {
            "type": "orchestrator",
            "request_id": result.get("request_id"),
            "final_decision": result.get("final_decision"),
            "agent_decisions": result.get("agent_decisions"),
            "agents_executed": result.get("agents_executed"),
            "execution_time_ms": result.get("execution_time_ms"),
        }


@router.get("/context/{workflow_id}", response_model=dict)
async def get_workflow_context(
    workflow_id: UUID,
    include_history: bool = True,
    include_similar: bool = False,
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Get the rich context that would be provided to agents.
    
    Useful for understanding what data agents see when making decisions.
    """
    integration = get_agent_workflow_integration(org_id)
    
    context = await integration.build_context(
        workflow_id=workflow_id,
        include_history=include_history,
        include_similar=include_similar,
    )
    
    return {
        "workflow_id": str(context.workflow_id),
        "workflow": context.workflow.to_dict() if context.workflow else None,
        "sla": {
            "instance": context.sla_instance,
            "definition": context.sla_definition,
        } if context.sla_instance else None,
        "policies": {
            "count": len(context.applicable_policies),
            "policies": context.applicable_policies[:5],  # First 5
        },
        "history": {
            "event_count": len(context.recent_events),
            "recent_events": context.recent_events[:10],  # Last 10
        },
        "similar_workflows": [
            {"id": str(w.get("id")), "state": w.get("current_state")}
            for w in context.similar_workflows[:3]
        ] if context.similar_workflows else [],
        "customer_tier": context.customer_tier,
        "tags": context.tags,
    }


@router.post("/decisions/{workflow_id}/review", response_model=dict)
async def review_decision(
    workflow_id: UUID,
    request: DecisionReviewRequest,
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Review and acknowledge an agent decision.
    
    This records the human's acceptance or rejection of the
    agent's recommendation for audit purposes.
    """
    integration = get_agent_workflow_integration(org_id)
    
    user_id = UUID(current_user.get("sub"))
    
    await integration.acknowledge_decision(
        workflow_id=workflow_id,
        decision_id=request.decision_id,
        user_id=user_id,
        accepted=request.accepted,
        feedback=request.feedback,
    )
    
    return {
        "status": "reviewed",
        "decision_id": str(request.decision_id),
        "accepted": request.accepted,
        "reviewer_id": str(user_id),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/decisions/{workflow_id}/apply", response_model=dict)
async def apply_recommendation(
    workflow_id: UUID,
    request: ApplyRecommendationRequest,
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Apply an agent's recommendation to the workflow.
    
    The HUMAN initiates this action - maintaining accountability.
    The agent only recommended the action; human approves and executes.
    
    Supported actions:
    - transition: Change workflow state (params: to_state)
    - assign: Assign to user (params: assignee_id)
    - escalate: Escalate workflow (params: reason, level)
    """
    integration = get_agent_workflow_integration(org_id)
    
    user_id = UUID(current_user.get("sub"))
    
    result = await integration.apply_recommendation(
        workflow_id=workflow_id,
        decision_id=request.decision_id,
        user_id=user_id,
        action=request.action,
        parameters=request.parameters,
    )
    
    return {
        "workflow_id": str(workflow_id),
        "decision_id": str(request.decision_id),
        **result,
        "applied_by": str(user_id),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/decisions/{workflow_id}/history", response_model=dict)
async def get_decision_history(
    workflow_id: UUID,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Get history of agent decisions for a workflow.
    
    Shows all agent decisions, reviews, and applied recommendations.
    """
    from app.services.event_store import event_store
    from app.models.event import EventType
    
    # Get all agent-related events for this workflow
    events = await event_store.get_stream_events(
        org_id=org_id,
        stream_id=workflow_id,
        limit=limit * 3,  # Fetch more to filter
    )
    
    agent_events = [
        e for e in events
        if e.event_type in [
            EventType.AGENT_DECISION,
            EventType.AGENT_DECISION_REVIEWED,
            EventType.AGENT_RECOMMENDATION_APPLIED,
        ]
    ][:limit]
    
    return {
        "workflow_id": str(workflow_id),
        "decision_count": len(agent_events),
        "decisions": [
            {
                "id": str(e.id),
                "event_type": e.event_type.value,
                "data": e.data,
                "timestamp": e.timestamp.isoformat(),
                "actor_id": str(e.actor_id) if e.actor_id else None,
                "actor_type": e.actor_type,
            }
            for e in agent_events
        ],
    }


@router.get("/trigger-points", response_model=dict)
async def list_trigger_points():
    """List available agent trigger points."""
    return {
        "trigger_points": [
            {
                "name": tp.value,
                "description": _get_trigger_description(tp),
            }
            for tp in AgentTriggerPoint
        ],
    }


def _get_trigger_description(trigger_point: AgentTriggerPoint) -> str:
    """Get description for a trigger point."""
    descriptions = {
        AgentTriggerPoint.WORKFLOW_CREATED: "When a new workflow is created",
        AgentTriggerPoint.WORKFLOW_STARTED: "When a workflow transitions to active",
        AgentTriggerPoint.WORKFLOW_TRANSITIONED: "When workflow state changes",
        AgentTriggerPoint.SLA_WARNING: "When SLA warning threshold is crossed",
        AgentTriggerPoint.SLA_BREACH: "When SLA is breached",
        AgentTriggerPoint.MANUAL_REQUEST: "Manual agent invocation via API",
        AgentTriggerPoint.PERIODIC_CHECK: "Scheduled periodic analysis",
        AgentTriggerPoint.ESCALATION_NEEDED: "When human escalation is required",
    }
    return descriptions.get(trigger_point, "Unknown trigger point")
