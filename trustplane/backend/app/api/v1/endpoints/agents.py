"""
Agent API Endpoints

REST API for agent operations - analysis, decisions, and orchestration.
Agents only recommend actions - execution goes through workflow system.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.core.auth import get_current_user, get_current_org_id
from app.core.database import get_supabase
from app.agents import (
    AgentContext, AgentDecision,
    create_sla_agent, create_workflow_agent, create_triage_agent,
    get_orchestrator,
)
from app.services.audit_service import AuditService
from app.models.audit import AuditCreate, AuditEventType, AuditActionType


router = APIRouter(prefix="/agents", tags=["agents"])


# Request/Response Models

class AgentContextRequest(BaseModel):
    """Request to create agent context."""
    workflow_id: Optional[UUID] = None
    sla_id: Optional[UUID] = None
    
    # Workflow context
    workflow_state: Optional[str] = None
    workflow_priority: Optional[str] = None
    workflow_created_at: Optional[datetime] = None
    workflow_owner_id: Optional[str] = None
    
    # SLA context
    sla_deadline: Optional[datetime] = None
    sla_time_remaining_seconds: Optional[int] = None
    sla_breach_level: Optional[str] = None
    sla_is_paused: Optional[bool] = None
    
    # Additional context
    title: Optional[str] = None
    description: Optional[str] = None
    customer_tier: Optional[str] = None
    
    # Historical context (optional)
    event_history: list[dict] = Field(default_factory=list)
    similar_workflows: list[dict] = Field(default_factory=list)


class AgentRunRequest(BaseModel):
    """Request to run a specific agent."""
    agent_type: str = Field(..., pattern="^(sla|workflow|triage)$")
    context: AgentContextRequest


class OrchestratorRunRequest(BaseModel):
    """Request to run the full agent orchestrator."""
    context: AgentContextRequest
    parallel: bool = True


class AgentDecisionResponse(BaseModel):
    """Response containing agent decision."""
    id: UUID
    agent_type: str
    decision_type: str
    confidence: str
    reasoning: str
    evidence: list[str]
    recommendations: list[str]
    suggested_action: Optional[str]
    requires_human_review: bool
    is_urgent: bool
    processing_time_ms: float
    timestamp: datetime


class OrchestratorResponse(BaseModel):
    """Response from orchestrator run."""
    request_id: str
    final_decision: dict
    agent_decisions: dict
    agents_executed: list[str]
    errors: list[dict]
    started_at: str
    completed_at: str
    execution_time_ms: Optional[float] = None


# Endpoints

@router.post("/run", response_model=dict)
async def run_agent(
    request: AgentRunRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
    supabase = Depends(get_supabase),
):
    """
    Run a specific agent for analysis and decision.
    
    Agent Types:
    - sla: SLA risk assessment
    - workflow: Workflow state analysis
    - triage: Request classification
    
    Returns the agent's decision (recommendation only - no mutations).
    """
    # Build context
    context = AgentContext(
        org_id=org_id,
        workflow_id=request.context.workflow_id,
        sla_id=request.context.sla_id,
        workflow_state=request.context.workflow_state,
        workflow_priority=request.context.workflow_priority,
        workflow_created_at=request.context.workflow_created_at,
        workflow_owner_id=request.context.workflow_owner_id,
        sla_deadline=request.context.sla_deadline,
        sla_time_remaining_seconds=request.context.sla_time_remaining_seconds,
        sla_breach_level=request.context.sla_breach_level,
        sla_is_paused=request.context.sla_is_paused,
        event_history=request.context.event_history,
        similar_workflows=request.context.similar_workflows,
        user_id=current_user.get("sub"),
        metadata={
            "title": request.context.title,
            "description": request.context.description,
            "customer_tier": request.context.customer_tier,
        }
    )
    
    # Create agent
    agents = {
        "sla": create_sla_agent,
        "workflow": create_workflow_agent,
        "triage": create_triage_agent,
    }
    
    agent_factory = agents.get(request.agent_type)
    if not agent_factory:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {request.agent_type}")
    
    agent = agent_factory()
    
    # Run agent
    decision = await agent.run(context)
    
    # Log to audit
    background_tasks.add_task(
        _log_agent_decision,
        supabase,
        org_id,
        current_user.get("sub"),
        request.agent_type,
        decision,
    )
    
    return {
        "id": str(decision.id),
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
        "processing_time_ms": decision.processing_time_ms,
        "decision_hash": decision.decision_hash,
        "timestamp": decision.timestamp.isoformat(),
    }


@router.post("/orchestrate", response_model=dict)
async def run_orchestrator(
    request: OrchestratorRunRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
    supabase = Depends(get_supabase),
):
    """
    Run the full agent orchestrator.
    
    Executes all agents (SLA, Workflow, Triage) and synthesizes
    their decisions into a unified recommendation.
    
    Set `parallel=true` for faster execution (agents run concurrently).
    """
    # Build context
    context = AgentContext(
        org_id=org_id,
        workflow_id=request.context.workflow_id,
        sla_id=request.context.sla_id,
        workflow_state=request.context.workflow_state,
        workflow_priority=request.context.workflow_priority,
        workflow_created_at=request.context.workflow_created_at,
        workflow_owner_id=request.context.workflow_owner_id,
        sla_deadline=request.context.sla_deadline,
        sla_time_remaining_seconds=request.context.sla_time_remaining_seconds,
        sla_breach_level=request.context.sla_breach_level,
        sla_is_paused=request.context.sla_is_paused,
        event_history=request.context.event_history,
        similar_workflows=request.context.similar_workflows,
        user_id=current_user.get("sub"),
        metadata={
            "title": request.context.title,
            "description": request.context.description,
            "customer_tier": request.context.customer_tier,
        }
    )
    
    # Get orchestrator
    orchestrator = get_orchestrator()
    
    # Run orchestration
    result = await orchestrator.run(org_id, context)
    
    # Log to audit
    background_tasks.add_task(
        _log_orchestrator_run,
        supabase,
        org_id,
        current_user.get("sub"),
        result,
    )
    
    return result


@router.post("/analyze/sla", response_model=dict)
async def analyze_sla_risk(
    workflow_id: UUID,
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
    supabase = Depends(get_supabase),
):
    """
    Quick SLA risk analysis for a workflow.
    
    Fetches workflow and SLA data, runs SLA agent, returns risk assessment.
    """
    # Fetch workflow data from database
    workflow_response = await supabase.table("workflows").select("*").eq(
        "id", str(workflow_id)
    ).eq("org_id", str(org_id)).execute()
    
    if not workflow_response.data:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    workflow = workflow_response.data[0]
    
    # Fetch associated SLA
    sla_response = await supabase.table("sla_instances").select("*").eq(
        "workflow_id", str(workflow_id)
    ).execute()
    
    sla = sla_response.data[0] if sla_response.data else None
    
    # Build context
    context = AgentContext(
        org_id=org_id,
        workflow_id=workflow_id,
        sla_id=UUID(sla["id"]) if sla else None,
        workflow_state=workflow.get("state"),
        workflow_priority=workflow.get("priority"),
        workflow_created_at=datetime.fromisoformat(workflow["created_at"].replace("Z", "+00:00")) if workflow.get("created_at") else None,
        workflow_owner_id=workflow.get("owner_id"),
        sla_deadline=datetime.fromisoformat(sla["deadline"].replace("Z", "+00:00")) if sla and sla.get("deadline") else None,
        sla_time_remaining_seconds=sla.get("time_remaining_seconds") if sla else None,
        sla_breach_level=sla.get("breach_level") if sla else None,
        sla_is_paused=sla.get("is_paused") if sla else None,
        user_id=current_user.get("sub"),
    )
    
    # Run SLA agent
    agent = create_sla_agent()
    decision = await agent.run(context)
    
    return {
        "workflow_id": str(workflow_id),
        "sla_id": str(sla["id"]) if sla else None,
        "risk_assessment": {
            "decision_type": decision.decision_type.value,
            "confidence": decision.confidence.value,
            "reasoning": decision.reasoning,
            "evidence": decision.evidence,
            "recommendations": decision.recommendations,
            "requires_human_review": decision.requires_human_review,
            "is_urgent": decision.is_urgent,
        },
        "timestamp": decision.timestamp.isoformat(),
    }


@router.get("/types", response_model=dict)
async def list_agent_types():
    """List available agent types and their capabilities."""
    return {
        "agents": [
            {
                "type": "sla",
                "name": "SLA Risk Agent",
                "description": "Analyzes SLA compliance and predicts breach risk",
                "capabilities": [
                    "Monitor SLA timers",
                    "Predict breach probability",
                    "Recommend escalations",
                    "Suggest priority adjustments",
                ],
            },
            {
                "type": "workflow",
                "name": "Workflow Agent",
                "description": "Analyzes workflow state and recommends transitions",
                "capabilities": [
                    "State transition recommendations",
                    "Bottleneck detection",
                    "Assignee suggestions",
                    "Completion estimates",
                ],
            },
            {
                "type": "triage",
                "name": "Triage Agent",
                "description": "Classifies and routes incoming requests",
                "capabilities": [
                    "Category classification",
                    "Priority determination",
                    "Team routing",
                    "Duplicate detection",
                ],
            },
        ],
        "orchestrator": {
            "description": "Runs all agents and synthesizes their decisions",
            "execution_modes": ["sequential", "parallel"],
        },
    }


@router.get("/decision-types", response_model=dict)
async def list_decision_types():
    """List possible decision types from agents."""
    return {
        "decision_types": [
            {"type": "approve", "description": "Approve the action/workflow"},
            {"type": "reject", "description": "Reject the action/workflow"},
            {"type": "escalate", "description": "Escalate to human review"},
            {"type": "defer", "description": "Defer decision, need more info"},
            {"type": "recommend", "description": "Provide recommendation"},
            {"type": "alert", "description": "Alert about a condition"},
        ],
        "confidence_levels": [
            {"level": "high", "description": ">90% confident, can auto-execute"},
            {"level": "medium", "description": "70-90%, recommend but verify"},
            {"level": "low", "description": "<70%, requires human review"},
        ],
    }


async def _log_agent_decision(
    supabase,
    org_id: UUID,
    user_id: str,
    agent_type: str,
    decision: AgentDecision,
):
    """Log agent decision to audit trail."""
    try:
        audit_service = AuditService(supabase, org_id)
        await audit_service.log_event(
            AuditCreate(
                event_type=AuditEventType.AGENT_DECISION_MADE,
                action=AuditActionType.EXECUTE,
                actor_id=f"agent:{agent_type}",
                actor_type="agent",
                description=f"Agent {agent_type} made decision: {decision.decision_type.value}",
                details={
                    "agent_type": agent_type,
                    "decision_type": decision.decision_type.value,
                    "confidence": decision.confidence.value,
                    "requires_human_review": decision.requires_human_review,
                    "is_urgent": decision.is_urgent,
                    "recommendations_count": len(decision.recommendations),
                },
            )
        )
    except Exception:
        pass  # Don't fail the request if audit logging fails


async def _log_orchestrator_run(
    supabase,
    org_id: UUID,
    user_id: str,
    result: dict,
):
    """Log orchestrator run to audit trail."""
    try:
        audit_service = AuditService(supabase, org_id)
        final_decision = result.get("final_decision", {})
        await audit_service.log_event(
            AuditCreate(
                event_type=AuditEventType.AGENT_DECISION_MADE,
                action=AuditActionType.EXECUTE,
                actor_id="agent:orchestrator",
                actor_type="agent",
                description=f"Orchestrator synthesized decision: {final_decision.get('decision_type', 'unknown')}",
                details={
                    "request_id": result.get("request_id"),
                    "agents_executed": result.get("agents_executed", []),
                    "errors_count": len(result.get("errors", [])),
                    "decision_type": final_decision.get("decision_type"),
                    "confidence": final_decision.get("confidence"),
                    "execution_time_ms": result.get("execution_time_ms"),
                },
            )
        )
    except Exception:
        pass
