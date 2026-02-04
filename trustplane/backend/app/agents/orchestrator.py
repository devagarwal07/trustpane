"""
Agent Orchestrator

LangGraph-based orchestration of multiple agents.
Coordinates agent execution and synthesizes decisions.
"""

from typing import Any, Optional, TypedDict, Annotated
from datetime import datetime
from uuid import UUID, uuid4
from dataclasses import dataclass, field
import asyncio
import operator

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.agents.base import (
    AgentState, AgentContext, AgentDecision, DecisionType,
    DecisionConfidence, AgentType
)
from app.agents.sla_agent import SLAAgent, create_sla_agent
from app.agents.workflow_agent import WorkflowAgent, create_workflow_agent
from app.agents.triage_agent import TriageAgent, create_triage_agent


class GraphState(TypedDict):
    """State passed through the agent graph."""
    # Input
    org_id: str
    request_id: str
    context: dict
    
    # Agent outputs
    sla_decision: Optional[dict]
    workflow_decision: Optional[dict]
    triage_decision: Optional[dict]
    
    # Synthesized output
    final_decision: Optional[dict]
    
    # Execution tracking
    agents_executed: Annotated[list[str], operator.add]
    errors: Annotated[list[dict], operator.add]
    
    # Metadata
    started_at: str
    completed_at: Optional[str]


class AgentOrchestrator:
    """
    Orchestrates multiple agents using LangGraph.
    
    Graph Structure:
    
        START
          │
          ├──► SLA Agent ────────┐
          │                      │
          ├──► Workflow Agent ───┼──► Synthesizer ──► END
          │                      │
          └──► Triage Agent ─────┘
    
    Agents run in parallel (when possible), then synthesizer
    combines their decisions into a final recommendation.
    """
    
    def __init__(self):
        self.sla_agent = create_sla_agent()
        self.workflow_agent = create_workflow_agent()
        self.triage_agent = create_triage_agent()
        
        # Build the graph
        self.graph = self._build_graph()
        self.memory = MemorySaver()
        self.app = self.graph.compile(checkpointer=self.memory)
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph agent graph."""
        graph = StateGraph(GraphState)
        
        # Add nodes
        graph.add_node("sla_agent", self._run_sla_agent)
        graph.add_node("workflow_agent", self._run_workflow_agent)
        graph.add_node("triage_agent", self._run_triage_agent)
        graph.add_node("synthesizer", self._synthesize_decisions)
        
        # Add edges - parallel execution then synthesis
        graph.set_entry_point("sla_agent")
        
        # All agents feed into synthesizer
        graph.add_edge("sla_agent", "workflow_agent")
        graph.add_edge("workflow_agent", "triage_agent")
        graph.add_edge("triage_agent", "synthesizer")
        graph.add_edge("synthesizer", END)
        
        return graph
    
    async def _run_sla_agent(self, state: GraphState) -> GraphState:
        """Run SLA agent node."""
        try:
            context = AgentContext(**state["context"])
            decision = await self.sla_agent.run(context)
            
            return {
                **state,
                "sla_decision": decision.model_dump(),
                "agents_executed": ["sla_agent"],
            }
        except Exception as e:
            return {
                **state,
                "sla_decision": None,
                "agents_executed": ["sla_agent"],
                "errors": [{"agent": "sla_agent", "error": str(e)}],
            }
    
    async def _run_workflow_agent(self, state: GraphState) -> GraphState:
        """Run workflow agent node."""
        try:
            context = AgentContext(**state["context"])
            decision = await self.workflow_agent.run(context)
            
            return {
                **state,
                "workflow_decision": decision.model_dump(),
                "agents_executed": ["workflow_agent"],
            }
        except Exception as e:
            return {
                **state,
                "workflow_decision": None,
                "agents_executed": ["workflow_agent"],
                "errors": [{"agent": "workflow_agent", "error": str(e)}],
            }
    
    async def _run_triage_agent(self, state: GraphState) -> GraphState:
        """Run triage agent node."""
        try:
            context = AgentContext(**state["context"])
            decision = await self.triage_agent.run(context)
            
            return {
                **state,
                "triage_decision": decision.model_dump(),
                "agents_executed": ["triage_agent"],
            }
        except Exception as e:
            return {
                **state,
                "triage_decision": None,
                "agents_executed": ["triage_agent"],
                "errors": [{"agent": "triage_agent", "error": str(e)}],
            }
    
    async def _synthesize_decisions(self, state: GraphState) -> GraphState:
        """Synthesize agent decisions into final recommendation."""
        sla_decision = state.get("sla_decision")
        workflow_decision = state.get("workflow_decision")
        triage_decision = state.get("triage_decision")
        
        # Collect all decisions
        decisions = []
        if sla_decision:
            decisions.append(("sla", sla_decision))
        if workflow_decision:
            decisions.append(("workflow", workflow_decision))
        if triage_decision:
            decisions.append(("triage", triage_decision))
        
        if not decisions:
            # No decisions available
            final = self._create_fallback_decision(state)
        else:
            final = self._merge_decisions(decisions)
        
        return {
            **state,
            "final_decision": final,
            "completed_at": datetime.utcnow().isoformat(),
            "agents_executed": ["synthesizer"],
        }
    
    def _merge_decisions(self, decisions: list[tuple[str, dict]]) -> dict:
        """Merge multiple agent decisions into unified decision."""
        # Collect all recommendations
        all_recommendations = []
        all_evidence = []
        reasoning_parts = []
        
        # Track urgency and human review needs
        requires_human = False
        is_urgent = False
        
        # Track decision types (use most severe)
        decision_type_priority = {
            "escalate": 5,
            "alert": 4,
            "reject": 3,
            "defer": 2,
            "recommend": 1,
            "approve": 0,
        }
        highest_priority_type = "approve"
        highest_priority = 0
        
        # Track confidence (use lowest)
        confidence_values = {"high": 3, "medium": 2, "low": 1}
        lowest_confidence = "high"
        lowest_confidence_value = 3
        
        for agent_name, decision in decisions:
            # Merge recommendations
            recs = decision.get("recommendations", [])
            for rec in recs:
                if rec not in all_recommendations:
                    all_recommendations.append(rec)
            
            # Merge evidence
            evidence = decision.get("evidence", [])
            for ev in evidence:
                if ev not in all_evidence:
                    all_evidence.append(ev)
            
            # Add reasoning
            reasoning = decision.get("reasoning", "")
            if reasoning:
                reasoning_parts.append(f"[{agent_name}] {reasoning}")
            
            # Check flags
            if decision.get("requires_human_review"):
                requires_human = True
            if decision.get("is_urgent"):
                is_urgent = True
            
            # Check decision type
            dtype = decision.get("decision_type", "recommend")
            if decision_type_priority.get(dtype, 0) > highest_priority:
                highest_priority = decision_type_priority.get(dtype, 0)
                highest_priority_type = dtype
            
            # Check confidence
            conf = decision.get("confidence", "medium")
            if confidence_values.get(conf, 2) < lowest_confidence_value:
                lowest_confidence_value = confidence_values.get(conf, 2)
                lowest_confidence = conf
        
        # Build final decision
        return {
            "id": str(uuid4()),
            "agent_type": "orchestrator",
            "decision_type": highest_priority_type,
            "confidence": lowest_confidence,
            "reasoning": " | ".join(reasoning_parts),
            "evidence": all_evidence[:10],  # Limit evidence
            "recommendations": all_recommendations[:10],  # Limit recommendations
            "suggested_action": all_recommendations[0] if all_recommendations else None,
            "requires_human_review": requires_human,
            "is_urgent": is_urgent,
            "source_decisions": {
                agent_name: {
                    "decision_type": dec.get("decision_type"),
                    "confidence": dec.get("confidence"),
                }
                for agent_name, dec in decisions
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    def _create_fallback_decision(self, state: GraphState) -> dict:
        """Create fallback decision when no agents succeed."""
        return {
            "id": str(uuid4()),
            "agent_type": "orchestrator",
            "decision_type": "escalate",
            "confidence": "low",
            "reasoning": "No agent decisions available - escalating to human review",
            "evidence": [f"Errors: {len(state.get('errors', []))}"],
            "recommendations": ["Requires human review - agent processing failed"],
            "requires_human_review": True,
            "is_urgent": True,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    async def run(
        self,
        org_id: UUID,
        context: AgentContext,
        thread_id: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Execute the agent graph.
        
        Args:
            org_id: Organization ID
            context: Agent context
            thread_id: Optional thread ID for checkpointing
            
        Returns:
            Final decision and execution state
        """
        request_id = str(uuid4())
        thread_id = thread_id or request_id
        
        initial_state: GraphState = {
            "org_id": str(org_id),
            "request_id": request_id,
            "context": context.model_dump(),
            "sla_decision": None,
            "workflow_decision": None,
            "triage_decision": None,
            "final_decision": None,
            "agents_executed": [],
            "errors": [],
            "started_at": datetime.utcnow().isoformat(),
            "completed_at": None,
        }
        
        config = {"configurable": {"thread_id": thread_id}}
        
        # Run the graph
        result = await self.app.ainvoke(initial_state, config)
        
        return {
            "request_id": request_id,
            "org_id": str(org_id),
            "final_decision": result.get("final_decision"),
            "agent_decisions": {
                "sla": result.get("sla_decision"),
                "workflow": result.get("workflow_decision"),
                "triage": result.get("triage_decision"),
            },
            "agents_executed": result.get("agents_executed", []),
            "errors": result.get("errors", []),
            "started_at": result.get("started_at"),
            "completed_at": result.get("completed_at"),
        }
    
    async def run_single_agent(
        self,
        agent_type: str,
        context: AgentContext
    ) -> AgentDecision:
        """
        Run a single agent (for testing or targeted analysis).
        
        Args:
            agent_type: One of "sla", "workflow", "triage"
            context: Agent context
            
        Returns:
            Agent decision
        """
        agents = {
            "sla": self.sla_agent,
            "workflow": self.workflow_agent,
            "triage": self.triage_agent,
        }
        
        agent = agents.get(agent_type)
        if not agent:
            raise ValueError(f"Unknown agent type: {agent_type}")
        
        return await agent.run(context)


class ParallelOrchestrator(AgentOrchestrator):
    """
    Orchestrator that runs agents in parallel for better performance.
    """
    
    async def run(
        self,
        org_id: UUID,
        context: AgentContext,
        thread_id: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Execute agents in parallel.
        """
        request_id = str(uuid4())
        started_at = datetime.utcnow()
        
        # Run all agents in parallel
        results = await asyncio.gather(
            self.sla_agent.run(context),
            self.workflow_agent.run(context),
            self.triage_agent.run(context),
            return_exceptions=True
        )
        
        # Process results
        sla_decision = results[0] if not isinstance(results[0], Exception) else None
        workflow_decision = results[1] if not isinstance(results[1], Exception) else None
        triage_decision = results[2] if not isinstance(results[2], Exception) else None
        
        # Collect errors
        errors = []
        for i, (name, result) in enumerate([
            ("sla", results[0]),
            ("workflow", results[1]),
            ("triage", results[2])
        ]):
            if isinstance(result, Exception):
                errors.append({"agent": name, "error": str(result)})
        
        # Synthesize decisions
        decisions = []
        if sla_decision:
            decisions.append(("sla", sla_decision.model_dump()))
        if workflow_decision:
            decisions.append(("workflow", workflow_decision.model_dump()))
        if triage_decision:
            decisions.append(("triage", triage_decision.model_dump()))
        
        if decisions:
            final_decision = self._merge_decisions(decisions)
        else:
            final_decision = self._create_fallback_decision({"errors": errors})
        
        completed_at = datetime.utcnow()
        
        return {
            "request_id": request_id,
            "org_id": str(org_id),
            "final_decision": final_decision,
            "agent_decisions": {
                "sla": sla_decision.model_dump() if sla_decision else None,
                "workflow": workflow_decision.model_dump() if workflow_decision else None,
                "triage": triage_decision.model_dump() if triage_decision else None,
            },
            "agents_executed": ["sla_agent", "workflow_agent", "triage_agent", "synthesizer"],
            "errors": errors,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "execution_time_ms": (completed_at - started_at).total_seconds() * 1000,
        }


# Factory functions
def create_orchestrator() -> AgentOrchestrator:
    """Create standard orchestrator."""
    return AgentOrchestrator()


def create_parallel_orchestrator() -> ParallelOrchestrator:
    """Create parallel orchestrator for better performance."""
    return ParallelOrchestrator()


# Singleton instance
_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator() -> AgentOrchestrator:
    """Get or create the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ParallelOrchestrator()
    return _orchestrator
