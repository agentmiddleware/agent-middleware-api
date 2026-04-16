"""
Agent Intelligence Router
==========================
Natural language queries, autonomous decisions, self-healing,
and agent memory management.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime

from ..core.auth import verify_api_key
from ..services.agent_intelligence import get_agent_intelligence


router = APIRouter(
    prefix="/v1/ai",
    tags=["Agent Intelligence"],
    dependencies=[Depends(verify_api_key)],
)


# --- Request/Response Models ---

class DecisionRequest(BaseModel):
    """Request an autonomous decision."""
    agent_id: str = Field(..., description="The agent requesting the decision")
    context: dict = Field(..., description="Current context and state")
    options: list[str] | None = Field(None, description="Available action options")


class DecisionResponse(BaseModel):
    """Response containing the decision."""
    decision_id: str
    agent_id: str
    reasoning: str
    action: str
    confidence: float
    timestamp: datetime


class HealRequest(BaseModel):
    """Request automatic diagnosis and healing."""
    issue: str = Field(..., description="Description of the issue")
    context: dict = Field(..., description="Error logs, stack traces, config, etc.")


class HealResponse(BaseModel):
    """Response containing the diagnosis and fix."""
    heal_id: str
    issue: str
    diagnosis: str
    code_change: str | None
    fix_applied: bool
    success: bool
    error: str | None


class QueryRequest(BaseModel):
    """Natural language query about the system."""
    question: str = Field(..., description="The question to answer")
    data_context: dict | None = Field(
        None, description="Optional data to query against"
    )


class QueryResponse(BaseModel):
    """Response to a natural language query."""
    answer: str
    model: str


class RememberRequest(BaseModel):
    """Store a memory for an agent."""
    agent_id: str
    key: str
    value: str


class RecallRequest(BaseModel):
    """Recall memories for an agent."""
    agent_id: str
    key: str | None = None
    limit: int = 10


class MemoryResponse(BaseModel):
    """Retrieved memories."""
    memories: list[dict]


class LearnRequest(BaseModel):
    """Learn from an experience."""
    agent_id: str
    experience: dict


class LearnResponse(BaseModel):
    """Result of learning."""
    insight: str


# --- Endpoints ---

@router.post("/decide", response_model=DecisionResponse)
async def make_decision(request: DecisionRequest):
    """
    Make an autonomous decision based on context.

    The AI analyzes the situation and recommends the best action.
    """
    ai = get_agent_intelligence()
    await ai.initialize()

    decision = await ai.decide(
        agent_id=request.agent_id,
        context=request.context,
        options=request.options,
    )

    return DecisionResponse(
        decision_id=decision.decision_id,
        agent_id=decision.agent_id,
        reasoning=decision.reasoning,
        action=decision.action,
        confidence=decision.confidence,
        timestamp=decision.timestamp,
    )


@router.get("/decisions/{agent_id}", response_model=list[DecisionResponse])
async def get_decisions(agent_id: str, limit: int = 20):
    """Get recent decisions for an agent."""
    ai = get_agent_intelligence()
    decisions = ai.get_decisions(agent_id, limit)

    return [
        DecisionResponse(
            decision_id=d.decision_id,
            agent_id=d.agent_id,
            reasoning=d.reasoning,
            action=d.action,
            confidence=d.confidence,
            timestamp=d.timestamp,
        )
        for d in decisions
    ]


@router.post("/heal", response_model=HealResponse)
async def diagnose_and_heal(request: HealRequest):
    """
    Automatically diagnose and suggest a fix for an issue.

    The AI analyzes error logs and produces a potential fix.
    Note: Fixes are not auto-applied — human review recommended.
    """
    ai = get_agent_intelligence()
    await ai.initialize()

    result = await ai.diagnose_and_heal(
        issue=request.issue,
        context=request.context,
    )

    return HealResponse(
        heal_id=result.heal_id,
        issue=result.issue,
        diagnosis=result.diagnosis,
        code_change=result.code_change,
        fix_applied=result.fix_applied,
        success=result.success,
        error=result.error,
    )


@router.get("/heal/{heal_id}", response_model=HealResponse)
async def get_heal(heal_id: str):
    """Get a specific self-heal result."""
    ai = get_agent_intelligence()
    result = ai.get_heal(heal_id)

    if not result:
        raise HTTPException(status_code=404, detail="Heal not found")

    return HealResponse(
        heal_id=result.heal_id,
        issue=result.issue,
        diagnosis=result.diagnosis,
        code_change=result.code_change,
        fix_applied=result.fix_applied,
        success=result.success,
        error=result.error,
    )


@router.post("/query", response_model=QueryResponse)
async def query_natural_language(request: QueryRequest):
    """
    Ask questions about the system in natural language.

    The AI answers based on the provided data context or general knowledge.
    """
    ai = get_agent_intelligence()
    await ai.initialize()

    answer = await ai.query(
        question=request.question,
        data_context=request.data_context,
    )

    return QueryResponse(answer=answer, model="llm")


@router.post("/memory", status_code=201)
async def store_memory(request: RememberRequest):
    """Store a memory for an agent."""
    ai = get_agent_intelligence()
    await ai.initialize()

    await ai.remember(
        agent_id=request.agent_id,
        key=request.key,
        value=request.value,
    )

    return {"status": "stored", "agent_id": request.agent_id, "key": request.key}


@router.post("/memory/recall", response_model=MemoryResponse)
async def recall_memories(request: RecallRequest):
    """Recall memories for an agent."""
    ai = get_agent_intelligence()
    await ai.initialize()

    memories = await ai.recall(
        agent_id=request.agent_id,
        key=request.key,
        limit=request.limit,
    )

    return MemoryResponse(memories=memories)


@router.post("/learn", response_model=LearnResponse)
async def learn_from_experience(request: LearnRequest):
    """
    Learn from an experience.

    The AI extracts patterns and stores insights for future decisions.
    """
    ai = get_agent_intelligence()
    await ai.initialize()

    insight = await ai.learn(
        agent_id=request.agent_id,
        experience=request.experience,
    )

    return LearnResponse(insight=insight)
