"""
TrustPlane AI Agents

LangGraph-based agents for intelligent decision-making.
Agents ONLY make recommendations - they never mutate data directly.
All mutations go through the event-sourced workflow system.

Agent Architecture:
- BaseAgent: Foundation with analyze → decide pattern
- SLAAgent: SLA risk assessment and breach prediction
- WorkflowAgent: Workflow state analysis and transition recommendations
- TriageAgent: Request classification, prioritization, and routing
- AgentOrchestrator: LangGraph coordination of multiple agents

Key Principles:
1. Agents READ from database (via services)
2. Agents WRITE only decision events
3. NO direct mutations - all changes via event sourcing
4. Deterministic reasoning (temperature=0)
5. Human escalation for low confidence decisions
"""

from app.agents.base import (
    BaseAgent,
    AgentState,
    AgentDecision,
    AgentContext,
    AgentType,
    DecisionType,
    DecisionConfidence,
)
from app.agents.sla_agent import SLAAgent, create_sla_agent
from app.agents.workflow_agent import WorkflowAgent, create_workflow_agent
from app.agents.triage_agent import TriageAgent, create_triage_agent
from app.agents.orchestrator import (
    AgentOrchestrator,
    ParallelOrchestrator,
    create_orchestrator,
    create_parallel_orchestrator,
    get_orchestrator,
)

__all__ = [
    # Base
    "BaseAgent",
    "AgentState",
    "AgentDecision",
    "AgentContext",
    "AgentType",
    "DecisionType",
    "DecisionConfidence",
    # Agents
    "SLAAgent",
    "WorkflowAgent",
    "TriageAgent",
    # Factories
    "create_sla_agent",
    "create_workflow_agent",
    "create_triage_agent",
    # Orchestration
    "AgentOrchestrator",
    "ParallelOrchestrator",
    "create_orchestrator",
    "create_parallel_orchestrator",
    "get_orchestrator",
]
