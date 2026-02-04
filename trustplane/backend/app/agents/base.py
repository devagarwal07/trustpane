"""
Base Agent Framework

Foundation for all AI agents in TrustPlane.
Agents follow strict rules:
1. READ from database via services
2. WRITE only decision events (no mutations)
3. NO direct side effects
4. Deterministic reasoning
5. Human escalation for low confidence
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
from uuid import UUID, uuid4
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
from pydantic import BaseModel, Field
import hashlib
import json


class AgentType(str, Enum):
    """Types of agents in the system."""
    SLA_RISK = "sla_risk"
    WORKFLOW = "workflow"
    TRIAGE = "triage"
    POLICY = "policy"
    INTEGRITY = "integrity"
    ESCALATION = "escalation"
    ORCHESTRATOR = "orchestrator"


class DecisionConfidence(str, Enum):
    """Confidence levels for agent decisions."""
    HIGH = "high"        # >90% confident, can auto-execute
    MEDIUM = "medium"    # 70-90%, recommend but verify
    LOW = "low"          # <70%, requires human review


class DecisionType(str, Enum):
    """Types of decisions agents can make."""
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"
    DEFER = "defer"
    RECOMMEND = "recommend"
    ALERT = "alert"


class AgentContext(BaseModel):
    """Context passed to agents for decision-making."""
    org_id: UUID
    request_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Target entity
    workflow_id: Optional[UUID] = None
    sla_id: Optional[UUID] = None
    event_id: Optional[UUID] = None
    
    # Workflow state
    workflow_state: Optional[str] = None
    workflow_priority: Optional[str] = None
    workflow_created_at: Optional[datetime] = None
    workflow_owner_id: Optional[str] = None
    
    # SLA context
    sla_deadline: Optional[datetime] = None
    sla_time_remaining_seconds: Optional[int] = None
    sla_breach_level: Optional[str] = None
    sla_is_paused: Optional[bool] = None
    
    # Historical context
    event_history: list[dict[str, Any]] = Field(default_factory=list)
    similar_workflows: list[dict[str, Any]] = Field(default_factory=list)
    
    # User context
    user_id: Optional[str] = None
    user_role: Optional[str] = None
    user_permissions: list[str] = Field(default_factory=list)
    
    # Additional data
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for LLM context."""
        return {
            "org_id": str(self.org_id),
            "request_id": str(self.request_id),
            "timestamp": self.timestamp.isoformat(),
            "workflow_id": str(self.workflow_id) if self.workflow_id else None,
            "sla_id": str(self.sla_id) if self.sla_id else None,
            "workflow_state": self.workflow_state,
            "workflow_priority": self.workflow_priority,
            "sla_deadline": self.sla_deadline.isoformat() if self.sla_deadline else None,
            "sla_time_remaining_seconds": self.sla_time_remaining_seconds,
            "sla_breach_level": self.sla_breach_level,
            "event_history_count": len(self.event_history),
            "user_role": self.user_role,
        }


class AgentDecision(BaseModel):
    """Structured decision output from an agent."""
    id: UUID = Field(default_factory=uuid4)
    agent_type: AgentType
    agent_id: str
    
    # Decision
    decision_type: DecisionType
    confidence: DecisionConfidence
    
    # Reasoning
    reasoning: str
    evidence: list[str] = Field(default_factory=list)
    
    # Recommendations
    recommendations: list[str] = Field(default_factory=list)
    suggested_action: Optional[str] = None
    suggested_assignee: Optional[str] = None
    
    # Flags
    requires_human_review: bool = False
    is_urgent: bool = False
    
    # Metadata
    processing_time_ms: float = 0.0
    model_used: Optional[str] = None
    tokens_used: int = 0
    
    # Integrity
    decision_hash: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    def compute_hash(self) -> str:
        """Compute integrity hash of decision."""
        content = {
            "agent_type": self.agent_type,
            "decision_type": self.decision_type,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "recommendations": self.recommendations,
            "timestamp": self.timestamp.isoformat(),
        }
        return hashlib.sha256(
            json.dumps(content, sort_keys=True).encode()
        ).hexdigest()
    
    def model_post_init(self, __context):
        """Compute hash after initialization."""
        if not self.decision_hash:
            self.decision_hash = self.compute_hash()


@dataclass
class AgentState:
    """Shared state across agent graph execution."""
    # Identifiers
    org_id: UUID
    request_id: UUID = field(default_factory=uuid4)
    
    # Input context
    context: AgentContext = None
    
    # Agent outputs (filled as agents execute)
    sla_analysis: Optional[dict[str, Any]] = None
    workflow_analysis: Optional[dict[str, Any]] = None
    triage_analysis: Optional[dict[str, Any]] = None
    policy_evaluation: Optional[dict[str, Any]] = None
    integrity_check: Optional[dict[str, Any]] = None
    
    # Final synthesized decision
    final_decision: Optional[AgentDecision] = None
    
    # Execution tracking
    agents_executed: list[str] = field(default_factory=list)
    execution_path: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    
    # Timing
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary."""
        return {
            "org_id": str(self.org_id),
            "request_id": str(self.request_id),
            "sla_analysis": self.sla_analysis,
            "workflow_analysis": self.workflow_analysis,
            "triage_analysis": self.triage_analysis,
            "policy_evaluation": self.policy_evaluation,
            "integrity_check": self.integrity_check,
            "final_decision": self.final_decision.model_dump() if self.final_decision else None,
            "agents_executed": self.agents_executed,
            "execution_path": self.execution_path,
            "errors": self.errors,
        }


class BaseAgent(ABC):
    """
    Base class for all AI agents.
    
    Rules:
    1. Agents READ from Postgres (via services)
    2. Agents WRITE only decision events
    3. NO direct side effects (no mutations, no external calls)
    4. Deterministic behavior where possible
    5. Human escalation for low confidence decisions
    """
    
    def __init__(
        self,
        agent_type: AgentType,
        agent_id: Optional[str] = None,
        model: str = "gpt-4o",
        temperature: float = 0.0,  # Deterministic
    ):
        self.agent_type = agent_type
        self.agent_id = agent_id or f"{agent_type.value}-{uuid4().hex[:8]}"
        self.model = model
        self.temperature = temperature
    
    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt for this agent."""
        pass
    
    @abstractmethod
    async def analyze(self, context: AgentContext) -> dict[str, Any]:
        """
        Analyze the given context and return findings.
        Must be implemented by each agent.
        """
        pass
    
    @abstractmethod
    async def decide(self, analysis: dict[str, Any], context: AgentContext) -> AgentDecision:
        """
        Make a decision based on analysis.
        Must be implemented by each agent.
        """
        pass
    
    async def run(self, context: AgentContext) -> AgentDecision:
        """
        Execute agent: analyze then decide.
        
        Args:
            context: Agent context
            
        Returns:
            AgentDecision
        """
        start_time = datetime.utcnow()
        
        try:
            # Analyze
            analysis = await self.analyze(context)
            
            # Decide
            decision = await self.decide(analysis, context)
            
            # Record timing
            end_time = datetime.utcnow()
            decision.processing_time_ms = (end_time - start_time).total_seconds() * 1000
            
            return decision
            
        except Exception as e:
            # Return error decision
            return AgentDecision(
                agent_type=self.agent_type,
                agent_id=self.agent_id,
                decision_type=DecisionType.ESCALATE,
                confidence=DecisionConfidence.LOW,
                reasoning=f"Agent error: {str(e)}",
                requires_human_review=True,
                is_urgent=True,
            )
    
    def _should_escalate(self, confidence: DecisionConfidence) -> bool:
        """Determine if decision should be escalated to human."""
        return confidence == DecisionConfidence.LOW
    
    def _calculate_confidence(self, factors: dict[str, float]) -> DecisionConfidence:
        """
        Calculate confidence based on weighted factors.
        
        Args:
            factors: Dict of factor name to score (0.0 to 1.0)
            
        Returns:
            DecisionConfidence
        """
        if not factors:
            return DecisionConfidence.LOW
        
        avg_score = sum(factors.values()) / len(factors)
        
        if avg_score >= 0.9:
            return DecisionConfidence.HIGH
        elif avg_score >= 0.7:
            return DecisionConfidence.MEDIUM
        else:
            return DecisionConfidence.LOW
