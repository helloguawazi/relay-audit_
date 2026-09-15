"""Prompt generation. Deterministic under a seed so cache prefixes are byte-identical."""

from __future__ import annotations

import hashlib
import random

WORDS = (
    "throughput latency prefill decode token stream gateway route failover upstream "
    "channel quota cache prefix suffix billing reconciliation audit probe handshake "
    "buffer chunk envelope payload corpus"
).split()


def filler(token_budget: int, seed: int, tag: str) -> str:
    """Deterministic filler of roughly `token_budget` tokens (~4 chars each)."""
    rng = random.Random(f"{seed}:{tag}")
    target_chars = token_budget * 4
    out: list[str] = []
    size = 0
    while size < target_chars:
        w = rng.choice(WORDS)
        out.append(w)
        size += len(w) + 1
    return " ".join(out)


def speed_prompt(token_budget: int, seed: int, n: int) -> str:
    """Short prompt. The marker keeps it out of the cache suite's namespace."""
    return (
        f"[speed-{n}] Reply with a single short sentence.\n\n"
        + filler(token_budget, seed, "speed")
    )


def cache_prompt(token_budget: int, seed: int, pass_id: str, cold_token: str) -> str:
    """Long prompt with a unique prefix, so the first pass cannot hit anyone's cache.

    `cold_token` must change between independent runs to force a genuinely cold
    first pass; reuse it across passes A and B so they share an identical prefix.
    """
    prefix = filler(token_budget, seed, f"cache-{cold_token}")
    digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:12]
    return (
        f"[cache-{pass_id}] Read the reference block below and answer with one word.\n"
        f"<!-- block {digest} -->\n{prefix}\n<!-- end block -->\n"
        f"Answer with the single word: ready"
    )


def billing_prompt(token_budget: int, seed: int) -> str:
    return (
        "[billing] Reply with the single word: ok.\n\n"
        + filler(token_budget, seed, "billing")
    )


def count_tokens_approx(text: str) -> int:
    """Character/4 heuristic. Reported alongside the exact count when tiktoken exists."""
    return max(1, len(text) // 4)


def count_tokens_exact(text: str) -> tuple[int | None, str]:
    """Exact token count when tiktoken is installed; otherwise None + reason."""
    try:
        import tiktoken  # type: ignore
    except Exception:
        return None, "tiktoken not installed"
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text)), "tiktoken cl100k_base"
    except Exception as exc:  # pragma: no cover - offline model download
        return None, f"tiktoken unavailable: {exc.__class__.__name__}"
