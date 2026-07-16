"""
Provider-agnostic LLM adapters for TagAssigner and divergence classification.

Call sites resolve per-task provider/model from settings via get_llm_client().
"""

from app.llm.factory import LLMTask, get_llm_client, resolve_task_config, reset_client_cache

__all__ = [
    "LLMTask",
    "get_llm_client",
    "resolve_task_config",
    "reset_client_cache",
]
