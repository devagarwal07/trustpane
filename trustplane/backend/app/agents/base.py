"""
Base Agent - Foundation for all AI agents
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass
from enum import Enum


class AgentType(str, Enum):
    """Agent types in the system"""
    SLA_RISK = "sla_risk"
    POLICY = "policy"
    INTEGRITY = "integrity"
    DECISION = "decision"


class DecisionConfidence(str, Enum):
    """Confidence levels for agent decisions"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class AgentDecision:
    """Structured agent decision output"""
    agent_type: AgentType
    decision: str
    confidence: DecisionConfidence
    reasoning: str
    recommendations: list
    requires_human_review: bool
    metadata: Dict[str, Any]
    timestamp: datetime


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
    
    def __init__(self, agent_type: AgentType):
        self.agent_type = agent_type
    
    @abstractmethod
    async def analyze(
        self,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze the given context and return findings.
        Must be implemented by each agent.
        """
        pass
    
    @abstractmethod
    async def decide(
        self,
        analysis: Dict[str, Any]
    ) -> AgentDecision:
        """
        Make a decision based on analysis.
        Must be implemented by each agent.
        """
        pass
    
    async def run(
        self,
        context: Dict[str, Any]
    ) -> AgentDecision:
        """
        Main agent execution flow.
        Analyze -> Decide -> Return structured decision
        """
        analysis = await self.analyze(context)
        decision = await self.decide(analysis)
        return decision
    
    def should_escalate(
        self,
        confidence: DecisionConfidence,
        decision_type: str
    ) -> bool:
        """Determine if decision should be escalated to human"""
        # Always escalate low confidence decisions
        if confidence == DecisionConfidence.LOW:
            return True
        
        # Escalate medium confidence for critical decisions
        critical_decisions = ["reject", "penalize", "terminate", "block"]
        if confidence == DecisionConfidence.MEDIUM and decision_type in critical_decisions:
            return True
        
        return False
