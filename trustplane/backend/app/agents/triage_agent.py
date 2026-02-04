"""
Triage Agent

Intelligent ticket/request triage for routing and prioritization.
Analyzes incoming requests and recommends appropriate handling.
"""

from typing import Any, Optional
from datetime import datetime
from uuid import UUID
import re

from app.agents.base import (
    BaseAgent, AgentType, AgentDecision, AgentContext,
    DecisionConfidence, DecisionType
)


class TriageAgent(BaseAgent):
    """
    Triage Agent for intelligent request routing.
    
    Responsibilities:
    - Classify incoming requests
    - Determine priority
    - Route to appropriate queue/team
    - Identify duplicate/related requests
    - Extract key entities and metadata
    
    Decision output includes:
    - Classification (category, subcategory)
    - Priority recommendation
    - Routing suggestion
    - Extracted entities
    """
    
    # Request categories
    CATEGORIES = {
        "technical": ["bug", "error", "crash", "performance", "integration"],
        "billing": ["invoice", "payment", "refund", "subscription", "pricing"],
        "account": ["password", "access", "permissions", "profile", "settings"],
        "feature": ["request", "enhancement", "suggestion", "feedback"],
        "support": ["help", "question", "guidance", "documentation"],
        "security": ["breach", "vulnerability", "attack", "unauthorized"],
        "compliance": ["audit", "regulation", "policy", "certification"],
    }
    
    # Priority keywords
    PRIORITY_INDICATORS = {
        "urgent": ["urgent", "critical", "emergency", "asap", "immediately", "outage", "down"],
        "high": ["important", "blocking", "major", "significant", "production"],
        "normal": ["normal", "standard", "regular", "typical"],
        "low": ["minor", "cosmetic", "nice-to-have", "when possible", "low priority"],
    }
    
    # Routing rules
    ROUTING_RULES = {
        "security": "security_team",
        "billing": "finance_team",
        "technical": "engineering_team",
        "compliance": "compliance_team",
        "account": "customer_success",
        "feature": "product_team",
        "support": "support_team",
    }
    
    def __init__(self, agent_id: Optional[str] = None):
        super().__init__(
            agent_type=AgentType.TRIAGE,
            agent_id=agent_id,
            model="gpt-4o",
            temperature=0.0,
        )
    
    @property
    def system_prompt(self) -> str:
        return """You are the Triage Agent for TrustPlane, a B2B SaaS platform.

Your role is to classify, prioritize, and route incoming requests intelligently.

RULES:
1. Always classify into a category and subcategory
2. Extract key entities (users, resources, dates, amounts)
3. Identify urgency signals
4. Consider customer tier/importance
5. Flag potential security issues
6. Identify related or duplicate requests
7. Provide clear routing recommendations

INPUTS YOU RECEIVE:
- Request title and description
- Customer information (tier, history)
- Related requests
- System context

OUTPUT (JSON):
{
    "category": "technical|billing|account|feature|support|security|compliance",
    "subcategory": "specific_type",
    "classification_confidence": 0.0 to 1.0,
    "priority": "urgent|high|normal|low",
    "priority_reasoning": "why this priority",
    "route_to": "team_name",
    "routing_reasoning": "why this team",
    "extracted_entities": {
        "users": ["user1", "user2"],
        "resources": ["resource1"],
        "dates": ["2024-01-01"],
        "amounts": ["$100"],
        "error_codes": ["ERR_001"]
    },
    "is_security_concern": boolean,
    "is_duplicate": boolean,
    "related_request_ids": ["id1", "id2"],
    "suggested_tags": ["tag1", "tag2"],
    "auto_response_suggested": boolean,
    "auto_response_template": "template_name" or null,
    "recommendations": ["action1", "action2"],
    "confidence": "high|medium|low",
    "reasoning": "detailed explanation"
}

CATEGORIES:
- technical: Software bugs, errors, performance issues
- billing: Invoices, payments, subscriptions
- account: Access, permissions, profile management
- feature: Feature requests, enhancements
- support: General help and questions
- security: Security concerns, vulnerabilities
- compliance: Regulatory, audit, policy matters

Remember: You analyze and recommend. You do NOT execute changes."""

    async def analyze(self, context: AgentContext) -> dict[str, Any]:
        """
        Analyze incoming request for triage.
        """
        analysis = {
            "timestamp": datetime.utcnow().isoformat(),
            "workflow_id": str(context.workflow_id) if context.workflow_id else None,
        }
        
        # Get request content from metadata
        title = context.metadata.get("title", "")
        description = context.metadata.get("description", "")
        content = f"{title} {description}".lower()
        
        analysis["content_length"] = len(content)
        analysis["title"] = title
        
        # Category classification
        analysis["category_analysis"] = self._classify_category(content)
        
        # Priority analysis
        analysis["priority_analysis"] = self._analyze_priority(content, context)
        
        # Entity extraction
        analysis["entities"] = self._extract_entities(content)
        
        # Security check
        analysis["security_check"] = self._check_security_concerns(content)
        
        # Customer context
        if context.metadata.get("customer_tier"):
            analysis["customer_tier"] = context.metadata.get("customer_tier")
            analysis["customer_adjustment"] = self._get_customer_adjustment(
                context.metadata.get("customer_tier")
            )
        
        # Related request analysis
        if context.similar_workflows:
            analysis["related_analysis"] = self._analyze_related(context.similar_workflows)
        else:
            analysis["related_analysis"] = {"has_related": False}
        
        return analysis
    
    async def decide(self, analysis: dict[str, Any], context: AgentContext) -> AgentDecision:
        """
        Make triage decision based on analysis.
        """
        category_analysis = analysis.get("category_analysis", {})
        priority_analysis = analysis.get("priority_analysis", {})
        security_check = analysis.get("security_check", {})
        entities = analysis.get("entities", {})
        related = analysis.get("related_analysis", {})
        
        # Determine category
        category = category_analysis.get("category", "support")
        subcategory = category_analysis.get("subcategory", "general")
        
        # Determine priority
        base_priority = priority_analysis.get("priority", "normal")
        
        # Adjust for security
        if security_check.get("is_concern"):
            if base_priority not in ["urgent", "high"]:
                base_priority = "high"
            category = "security"
        
        # Adjust for customer tier
        customer_adjustment = analysis.get("customer_adjustment", 0)
        priority = self._apply_customer_adjustment(base_priority, customer_adjustment)
        
        # Determine routing
        route_to = self.ROUTING_RULES.get(category, "support_team")
        
        # Check for duplicates
        is_duplicate = related.get("is_duplicate", False)
        related_ids = related.get("related_ids", [])
        
        # Build recommendations
        recommendations = []
        
        if is_duplicate:
            recommendations.append(f"Potential duplicate of {related_ids[0] if related_ids else 'existing request'}")
            recommendations.append("Review related requests before processing")
        
        if security_check.get("is_concern"):
            recommendations.append("Security review required")
            recommendations.append(f"Security indicators: {', '.join(security_check.get('indicators', []))}")
        
        if priority == "urgent":
            recommendations.append("Immediate attention required")
            recommendations.append("Notify on-call team")
        
        recommendations.append(f"Route to {route_to}")
        recommendations.append(f"Classify as {category}/{subcategory}")
        
        # Decision type
        if security_check.get("is_concern"):
            decision_type = DecisionType.ESCALATE
            requires_human = True
            is_urgent = True
        elif priority == "urgent":
            decision_type = DecisionType.ALERT
            requires_human = True
            is_urgent = True
        elif is_duplicate:
            decision_type = DecisionType.DEFER
            requires_human = True
            is_urgent = False
        else:
            decision_type = DecisionType.RECOMMEND
            requires_human = False
            is_urgent = False
        
        # Calculate confidence
        confidence_factors = {
            "category_confidence": category_analysis.get("confidence", 0.5),
            "priority_confidence": priority_analysis.get("confidence", 0.7),
            "content_available": 1.0 if analysis.get("content_length", 0) > 20 else 0.5,
        }
        confidence = self._calculate_confidence(confidence_factors)
        
        # Build reasoning
        reasoning_parts = [
            f"Classified as {category}/{subcategory}",
            f"Priority: {priority}",
            f"Route to: {route_to}",
        ]
        if security_check.get("is_concern"):
            reasoning_parts.append("Security concern detected")
        if is_duplicate:
            reasoning_parts.append("Potential duplicate identified")
        
        reasoning = ". ".join(reasoning_parts)
        
        # Evidence
        evidence = []
        if category_analysis.get("matched_keywords"):
            evidence.append(f"Category keywords: {', '.join(category_analysis.get('matched_keywords', [])[:3])}")
        if priority_analysis.get("matched_keywords"):
            evidence.append(f"Priority keywords: {', '.join(priority_analysis.get('matched_keywords', [])[:3])}")
        if entities.get("error_codes"):
            evidence.append(f"Error codes: {', '.join(entities.get('error_codes', []))}")
        
        return AgentDecision(
            agent_type=self.agent_type,
            agent_id=self.agent_id,
            decision_type=decision_type,
            confidence=confidence,
            reasoning=reasoning,
            evidence=evidence,
            recommendations=recommendations,
            suggested_action=f"route:{route_to}",
            suggested_assignee=None,
            requires_human_review=requires_human,
            is_urgent=is_urgent,
            model_used=self.model,
        )
    
    def _classify_category(self, content: str) -> dict[str, Any]:
        """Classify content into category."""
        scores = {}
        matched = {}
        
        for category, keywords in self.CATEGORIES.items():
            score = 0
            matches = []
            for keyword in keywords:
                if keyword in content:
                    score += 1
                    matches.append(keyword)
            scores[category] = score
            matched[category] = matches
        
        # Find best match
        best_category = max(scores, key=scores.get) if scores else "support"
        best_score = scores.get(best_category, 0)
        
        # Calculate confidence
        total_score = sum(scores.values())
        confidence = best_score / total_score if total_score > 0 else 0.5
        
        # Determine subcategory
        subcategory = matched.get(best_category, ["general"])[0] if matched.get(best_category) else "general"
        
        return {
            "category": best_category,
            "subcategory": subcategory,
            "confidence": round(confidence, 2),
            "matched_keywords": matched.get(best_category, []),
            "all_scores": scores,
        }
    
    def _analyze_priority(self, content: str, context: AgentContext) -> dict[str, Any]:
        """Analyze priority indicators."""
        scores = {"urgent": 0, "high": 0, "normal": 0, "low": 0}
        matched = {"urgent": [], "high": [], "normal": [], "low": []}
        
        for priority, keywords in self.PRIORITY_INDICATORS.items():
            for keyword in keywords:
                if keyword in content:
                    scores[priority] += 1
                    matched[priority].append(keyword)
        
        # Determine priority
        if scores["urgent"] > 0:
            priority = "urgent"
        elif scores["high"] > 0:
            priority = "high"
        elif scores["low"] > scores["normal"]:
            priority = "low"
        else:
            priority = "normal"
        
        # Confidence based on keyword matches
        total_matches = sum(scores.values())
        confidence = 0.9 if total_matches > 0 else 0.6
        
        return {
            "priority": priority,
            "confidence": confidence,
            "matched_keywords": matched.get(priority, []),
            "all_scores": scores,
        }
    
    def _extract_entities(self, content: str) -> dict[str, list[str]]:
        """Extract key entities from content."""
        entities = {
            "users": [],
            "emails": [],
            "error_codes": [],
            "urls": [],
            "amounts": [],
            "dates": [],
        }
        
        # Email pattern
        emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', content)
        entities["emails"] = emails
        
        # Error code pattern (common formats)
        error_codes = re.findall(r'(?:err(?:or)?[-_]?\d+|[A-Z]{2,5}[-_]\d{3,})', content, re.IGNORECASE)
        entities["error_codes"] = error_codes
        
        # URL pattern
        urls = re.findall(r'https?://[^\s]+', content)
        entities["urls"] = urls
        
        # Amount pattern
        amounts = re.findall(r'\$[\d,]+(?:\.\d{2})?', content)
        entities["amounts"] = amounts
        
        # Date pattern (simple)
        dates = re.findall(r'\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}', content)
        entities["dates"] = dates
        
        return entities
    
    def _check_security_concerns(self, content: str) -> dict[str, Any]:
        """Check for security-related concerns."""
        security_keywords = [
            "breach", "hack", "unauthorized", "attack", "vulnerability",
            "exploit", "malware", "phishing", "compromised", "leaked",
            "password stolen", "data theft", "ransomware", "intrusion"
        ]
        
        found = []
        for keyword in security_keywords:
            if keyword in content:
                found.append(keyword)
        
        return {
            "is_concern": len(found) > 0,
            "indicators": found,
            "severity": "critical" if len(found) > 2 else "high" if found else "none",
        }
    
    def _get_customer_adjustment(self, tier: str) -> int:
        """Get priority adjustment based on customer tier."""
        adjustments = {
            "enterprise": 2,
            "premium": 1,
            "standard": 0,
            "free": -1,
        }
        return adjustments.get(tier.lower(), 0)
    
    def _apply_customer_adjustment(self, priority: str, adjustment: int) -> str:
        """Apply customer tier adjustment to priority."""
        priorities = ["low", "normal", "high", "urgent"]
        
        try:
            current_index = priorities.index(priority)
            new_index = max(0, min(len(priorities) - 1, current_index + adjustment))
            return priorities[new_index]
        except ValueError:
            return priority
    
    def _analyze_related(self, similar_workflows: list[dict]) -> dict[str, Any]:
        """Analyze related/similar requests."""
        if not similar_workflows:
            return {"has_related": False}
        
        # Check for potential duplicates (high similarity)
        duplicates = []
        related = []
        
        for workflow in similar_workflows:
            similarity = workflow.get("similarity", 0)
            if similarity > 0.9:
                duplicates.append(str(workflow.get("id")))
            elif similarity > 0.5:
                related.append(str(workflow.get("id")))
        
        return {
            "has_related": len(related) > 0 or len(duplicates) > 0,
            "is_duplicate": len(duplicates) > 0,
            "duplicate_ids": duplicates,
            "related_ids": related,
            "total_similar": len(similar_workflows),
        }


# Factory function
def create_triage_agent(agent_id: Optional[str] = None) -> TriageAgent:
    """Create a triage agent instance."""
    return TriageAgent(agent_id=agent_id)
