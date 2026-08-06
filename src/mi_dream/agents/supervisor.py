from deepagents import SubAgent, create_deep_agent
from langchain_openai import ChatOpenAI

from mi_dream.agents.tools import make_recall_strategy_tool, make_save_reasoning_trace_tool
from mi_dream.config import settings

SUPERVISOR_PROMPT = """\
You are a Supervisor agent. Before planning any task:
1. Call recall_strategy to check for existing strategies.
2. If strategies are returned, use them to inform your plan.
3. After execution, call save_reasoning_trace to record your reasoning.
4. If your Research Agent finds data that contradicts a Strategy,
   explicitly signal the discrepancy in your response.
"""

RESEARCH_PROMPT = """\
You are the Research Agent. Gather evidence for the current task and report
findings concisely. Never call the knowledge tools; the Supervisor coordinates retrieval.
"""


def _build_model() -> ChatOpenAI:
    if not settings.llm_api_key:
        raise ValueError("LLM_API_KEY not set in environment")
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
    )


def create_supervisor(task_description: str, tenant_id: str = "default"):
    """Build a DeepAgents Supervisor graph (SDD §6) with knowledge tools + Research sub-agent."""
    tools = [
        make_recall_strategy_tool(tenant_id),
        make_save_reasoning_trace_tool(tenant_id),
    ]
    subagents = [
        SubAgent(
            name="research",
            description="Research Agent: investigates and gathers evidence for the task.",
            system_prompt=RESEARCH_PROMPT,
        )
    ]
    prompt = f"{SUPERVISOR_PROMPT}\nCurrent task: {task_description}"
    return create_deep_agent(
        model=_build_model(),
        tools=tools,
        system_prompt=prompt,
        subagents=subagents,
        name="mi-dream-supervisor",
    )
