"""Timing/token/cost capture around the two OpenAI calls in rag.py.

Modeled on alexeygrigorev/fitness-assistant's metrics.py (an
LLMCallRecord-shaped dataclass + a cost calculator), adapted to our two
actual calls (a tool-calling extraction + an embedding), not his single
chat-completion. This is NEW capability — the Node version never
captured any of this; it's what db_conversations.py logs per search.
"""
import time
from dataclasses import dataclass, field

# Per-1M-token USD pricing, best-effort. Only models this pipeline
# actually uses need an entry; an unlisted model returns cost=None rather
# than a silently wrong guess — better to show "unknown" than a fabricated
# number. Update if OpenAI's published pricing changes.
_PRICING_PER_1M = {
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
    # gpt-5.6-luna: standard pricing is $0.20/$1.20 per 1M input/output —
    # per an explicit 2026-08-31 request, priced here at the discounted
    # Batch API rate instead (a flat 50% off standard, OpenAI's
    # long-standing published Batch discount policy): $0.10/$0.60. Note
    # this pipeline actually calls the model synchronously (a live user
    # search), not through the async Batch endpoint, so the true incurred
    # cost is the $0.20/$1.20 standard rate — this deliberately
    # understates real spend as a lower-bound estimate, not an accounting
    # of what was actually billed. Confirmed via OpenRouter's own pricing
    # page (openrouter.ai/openai/gpt-5.6-luna) for the standard rate; the
    # batch discount is OpenAI's standard, consistently-documented policy
    # rather than a number specific to this one model.
    "gpt-5.6-luna": {"input": 0.10, "output": 0.60},
}


@dataclass
class LLMCallRecord:
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float | None = field(default=None)

    def __post_init__(self):
        pricing = _PRICING_PER_1M.get(self.model)
        if pricing is not None:
            self.cost_usd = round(
                self.input_tokens / 1_000_000 * pricing["input"]
                + self.output_tokens / 1_000_000 * pricing["output"],
                6,
            )


class Timer:
    """Small context-manager stopwatch — `with Timer() as t: ...` then
    `t.elapsed_ms`."""

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
        return False
