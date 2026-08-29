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
    # gpt-5.6-luna pricing not publicly listed as of this writing — left
    # unpriced on purpose (see the docstring above) rather than guessed.
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
