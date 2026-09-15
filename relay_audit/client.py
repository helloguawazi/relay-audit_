"""HTTP client: streaming measurement, usage normalisation, demo transport.

Design notes that matter for honesty:

* Retries default to 0. A retry hides a failure, and failures are data.
* Concurrency defaults to 1. Parallel requests contaminate latency measurement.
* TLS/connect time is recorded separately so a slow CDN cannot masquerade as
  slow inference.
* Every response is stored verbatim before any interpretation happens.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Endpoint


@dataclass
class Usage:
    """Normalised usage across OpenAI-shape and Anthropic-shape responses."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reported_total: int | None = None
    raw: dict = field(default_factory=dict)

    @property
    def has_any(self) -> bool:
        return any(
            v is not None
            for v in (self.input_tokens, self.output_tokens, self.cache_read_tokens, self.cache_write_tokens)
        )

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "reported_total": self.reported_total,
        }


@dataclass
class Result:
    """One measured request. Stored verbatim in raw.json."""

    endpoint_id: str
    suite: str
    label: str
    ok: bool
    status: int | None = None
    error: str | None = None
    model_requested: str | None = None
    model_echoed: str | None = None
    connect_ms: float | None = None
    ttft_ms: float | None = None
    total_ms: float | None = None
    completion_tokens: int | None = None
    content_chars: int = 0
    usage: Usage = field(default_factory=Usage)
    request_prompt_chars: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def tps(self) -> float | None:
        """Output tokens per second over the generation window."""
        if self.ttft_ms is None or self.total_ms is None or not self.completion_tokens:
            return None
        gen_ms = self.total_ms - self.ttft_ms
        if gen_ms <= 0:
            return None
        return self.completion_tokens / (gen_ms / 1000.0)

    def to_dict(self) -> dict:
        d = {
            "endpoint_id": self.endpoint_id,
            "suite": self.suite,
            "label": self.label,
            "ok": self.ok,
            "status": self.status,
            "error": self.error,
            "model_requested": self.model_requested,
            "model_echoed": self.model_echoed,
            "model_mismatch": bool(
                self.model_echoed and self.model_requested and self.model_echoed != self.model_requested
            ),
            "connect_ms": round(self.connect_ms, 2) if self.connect_ms is not None else None,
            "ttft_ms": round(self.ttft_ms, 2) if self.ttft_ms is not None else None,
            "total_ms": round(self.total_ms, 2) if self.total_ms is not None else None,
            "completion_tokens": self.completion_tokens,
            "tps": round(self.tps, 2) if self.tps is not None else None,
            "content_chars": self.content_chars,
            "request_prompt_chars": self.request_prompt_chars,
            "usage": self.usage.to_dict(),
        }
        if self.extra:
            d["extra"] = self.extra
        return d


def build_request(ep: Endpoint, prompt: str, max_tokens: int, stream: bool, model: str | None = None) -> dict:
    model = model or ep.model
    if ep.protocol == "anthropic":
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }
    else:
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
            "temperature": 0,
        }
        if stream:
            # Not all relays honour this; the fallback path re-requests without streaming.
            body["stream_options"] = {"include_usage": True}
    return body


def build_headers(ep: Endpoint, stream: bool = True) -> dict:
    key = ep.require_key()
    headers = {
        "Content-Type": "application/json",
        # Accept must reflect what was actually asked for, or a server that
        # negotiates on Accept sees a request no ordinary client would send.
        "Accept": "text/event-stream" if stream else "application/json",
        "User-Agent": "relay-audit/0.1",
    }
    if ep.demo:
        # Only sent in demo mode: real endpoints should see a request that is
        # byte-identical to what an ordinary client would send.
        headers["x-relay-audit-endpoint"] = ep.id
    if ep.protocol == "anthropic":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def parse_usage(protocol: str, payload: dict) -> Usage:
    """Normalise usage from either response shape. Absent fields stay None.

    Keeping them None rather than 0 matters: 'the provider did not report it'
    and 'the provider reported zero' are different findings.
    """
    u = payload.get("usage") or payload.get("message", {}).get("usage") or {}
    if not isinstance(u, dict):
        return Usage()
    usage = Usage(raw=u)

    if protocol == "anthropic":
        usage.input_tokens = _int(u.get("input_tokens"))
        usage.output_tokens = _int(u.get("output_tokens"))
        usage.cache_read_tokens = _int(u.get("cache_read_input_tokens"))
        usage.cache_write_tokens = _int(u.get("cache_creation_input_tokens"))
    else:
        usage.input_tokens = _int(u.get("prompt_tokens"))
        usage.output_tokens = _int(u.get("completion_tokens"))
        details = u.get("prompt_tokens_details") or {}
        cached = _int(details.get("cached_tokens")) if isinstance(details, dict) else None
        usage.cache_read_tokens = cached
        # Some relays report Anthropic-style fields on an OpenAI-shaped body.
        if usage.cache_read_tokens is None:
            usage.cache_read_tokens = _int(u.get("cache_read_input_tokens"))
        usage.cache_write_tokens = _int(u.get("cache_creation_input_tokens"))

    usage.reported_total = _int(u.get("total_tokens"))
    return usage


def _int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def sse_marker() -> str:
    return "data: [DONE]\n\n"


class _IterStream(httpx.SyncByteStream):
    """Byte stream backed by a generator, so the demo can space chunks in time."""

    def __init__(self, iterator) -> None:
        self._iterator = iterator

    def __iter__(self):
        return self._iterator

    def close(self) -> None:
        close = getattr(self._iterator, "close", None)
        if close is not None:
            close()


class DemoTransport(httpx.BaseTransport):
    """Synthetic transport for validating the harness without spending money.

    It deliberately produces a *mixed* result set so every report branch is
    exercised: one endpoint with an honest cache, one that fakes the counter
    without a real speedup, and occasional 429s.
    """

    def __init__(self, behavior: dict[str, str] | None = None) -> None:
        # behavior maps endpoint id -> "honest" | "counter-only-fake" | "no-cache"
        self.behavior = behavior or {}
        self._seen: dict[str, int] = {}
        self._counter = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self._counter += 1
        body = json.loads(request.content.decode("utf-8"))
        model = body.get("model", "unknown")
        ep_id = request.headers.get("x-relay-audit-endpoint", "")
        mode = self.behavior.get(ep_id, "honest")
        prompt = body["messages"][0]["content"]
        is_cache_pass = "[cache-" in prompt
        delay: float

        # 1 in 12 requests fails, to exercise the failure-rate path.
        if self._counter % 12 == 0:
            return httpx.Response(
                429,
                json={"error": {"message": "demo: simulated rate limit"}},
                request=request,
            )

        # The billing probes must actually fail in the demo, otherwise the
        # report's "probe did not fail" branch is never exercised and the demo
        # silently accuses every endpoint of accepting impossible requests.
        if model.startswith("__relay_audit_"):
            return httpx.Response(
                404,
                json={"error": {"message": f"demo: unknown model '{model}'", "type": "invalid_request_error"}},
                request=request,
            )
        if int(body.get("max_tokens", 0)) > 1_000_000:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "demo: max_tokens exceeds the model's output limit",
                        "type": "invalid_request_error",
                    }
                },
                request=request,
            )

        declared_read = 0
        declared_write = 0
        if is_cache_pass:
            self._seen[prompt] = self._seen.get(prompt, 0) + 1
            first_time = self._seen[prompt] == 1
            if mode == "counter-only-fake":
                # Declares a hit, but the wall clock stays flat. This is the
                # exact pattern the cache suite exists to catch.
                declared_read = 0 if first_time else 3200
                delay = 1.4
            elif mode == "no-cache":
                declared_read = 0
                delay = 1.4
            else:
                declared_read = 0 if first_time else 3200
                delay = 0.35 if not first_time else 1.4
                declared_write = 3200 if first_time else 0
        else:
            delay = 0.45

        prompt_tokens = len(prompt) // 4
        requested_max = int(body.get("max_tokens", 8))
        # Cap the synthetic body so the demo does not build gigabyte strings.
        completion_tokens = min(requested_max, 64)
        content = "ok" * max(1, completion_tokens // 2)

        if body.get("stream"):
            def sse(payload: dict) -> str:
                return "data: " + json.dumps(payload) + "\n\n"

            first = sse(
                {"id": "demo", "object": "chat.completion.chunk", "model": model,
                 "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
            )
            content_chunk = sse(
                {"id": "demo", "object": "chat.completion.chunk", "model": model,
                 "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]}
            )
            final = sse(
                {"id": "demo", "object": "chat.completion.chunk", "model": model,
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {
                     "prompt_tokens": prompt_tokens,
                     "completion_tokens": completion_tokens,
                     "total_tokens": prompt_tokens + completion_tokens,
                     "prompt_tokens_details": {"cached_tokens": declared_read},
                     "cache_creation_input_tokens": declared_write,
                 }}
            ) + sse_marker()

            # The delays are what make the demo exercise the cache suite's
            # physical-evidence check: a faked counter keeps the wall clock flat.
            def stream_body():
                yield first.encode("utf-8")
                time.sleep(delay)
                yield content_chunk.encode("utf-8")
                time.sleep(0.15)
                yield final.encode("utf-8")

            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=_IterStream(stream_body()),
                request=request,
            )

        # Non-streaming demo response. `ok` stays None when the counter is faked
        # so the report's model-identity column shows "—" instead of a match it
        # cannot actually vouch for.
        return httpx.Response(
            200,
            json={
                "id": "demo",
                "object": "chat.completion",
                "model": model if mode != "counter-only-fake" else None,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                             "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "prompt_tokens_details": {"cached_tokens": declared_read},
                    "cache_creation_input_tokens": declared_write,
                },
            },
            request=request,
        )


class Client:
    """Measures one request against one endpoint."""

    def __init__(self, ep: Endpoint, params, demo: bool = False, demo_behavior: dict | None = None) -> None:
        self.ep = ep
        self.params = params
        if demo:
            transport: httpx.BaseTransport = DemoTransport(demo_behavior)
        else:
            transport = httpx.HTTPTransport(retries=params.max_retries)
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(params.timeout_seconds),
            follow_redirects=False,
            headers={"Accept-Encoding": "identity"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def request(
        self,
        prompt: str,
        max_tokens: int,
        suite: str,
        label: str,
        stream: bool = True,
        model: str | None = None,
        extra: dict | None = None,
    ) -> Result:
        body = build_request(self.ep, prompt, max_tokens, stream, model=model)
        res = Result(
            endpoint_id=self.ep.id,
            suite=suite,
            label=label,
            ok=False,
            model_requested=body["model"],
            request_prompt_chars=len(prompt),
            extra=dict(extra or {}),
        )
        t0 = time.perf_counter()
        try:
            with self._client.stream(
                "POST", self.ep.url, json=body, headers=build_headers(self.ep, stream)
            ) as resp:
                t_headers = time.perf_counter()
                res.connect_ms = (t_headers - t0) * 1000.0
                res.status = resp.status_code

                if resp.status_code >= 400:
                    raw = resp.read().decode("utf-8", errors="replace")
                    res.error = f"HTTP {resp.status_code}: {raw[:400]}"
                    res.total_ms = (time.perf_counter() - t0) * 1000.0
                    return res

                if not stream:
                    raw = resp.read().decode("utf-8", errors="replace")
                    res.total_ms = (time.perf_counter() - t0) * 1000.0
                    self._consume_json(res, raw)
                    return res

                self._consume_stream(res, resp, t0)
                return res
        except httpx.TimeoutException as exc:
            res.error = f"timeout after {self.params.timeout_seconds}s: {exc.__class__.__name__}"
            res.total_ms = (time.perf_counter() - t0) * 1000.0
            return res
        except httpx.HTTPError as exc:
            res.error = f"{exc.__class__.__name__}: {exc}"
            res.total_ms = (time.perf_counter() - t0) * 1000.0
            return res

    def _consume_json(self, res: Result, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            res.error = f"non-JSON body: {raw[:300]}"
            return
        if "error" in payload and payload["error"]:
            res.error = f"error body: {json.dumps(payload['error'])[:300]}"
            return
        res.model_echoed = payload.get("model")
        content = ""
        choices = payload.get("choices") or []
        if choices:
            content = (choices[0].get("message") or {}).get("content") or ""
        elif "content" in payload:
            content = "".join(
                b.get("text", "") for b in payload.get("content", []) if isinstance(b, dict)
            )
        res.content_chars = len(content)
        res.usage = parse_usage(self.ep.protocol, payload)
        res.completion_tokens = res.usage.output_tokens
        res.ok = True

    def _consume_stream(self, res: Result, resp: httpx.Response, t0: float) -> None:
        ttft: float | None = None
        content_chars = 0
        usage_payload: dict | None = None
        seen_model: str | None = None
        error_text: str | None = None
        text_buf = ""
        data_lines: list[str] = []

        for chunk in resp.iter_text():
            if not chunk:
                continue
            text_buf += chunk
            while "\n" in text_buf:
                line, _, text_buf = text_buf.partition("\n")
                line = line.strip("\r").strip()
                if not line:
                    if data_lines:
                        payload_text = "\n".join(data_lines)
                        data_lines = []
                        if payload_text != "[DONE]":
                            try:
                                payload = json.loads(payload_text)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(payload, dict) and payload.get("error"):
                                error_text = json.dumps(payload["error"])[:300]
                                continue
                            if payload.get("model"):
                                seen_model = payload["model"]
                            if payload.get("usage"):
                                usage_payload = payload
                            delta = _extract_delta(self.ep.protocol, payload)
                            if delta:
                                content_chars += len(delta)
                                if ttft is None:
                                    ttft = time.perf_counter()
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif line.startswith(":") or line.startswith("event:") or line.startswith("id:"):
                    # Comment/keepalive or SSE event name. Not content.
                    continue

        res.total_ms = (time.perf_counter() - t0) * 1000.0
        res.ttft_ms = (ttft - t0) * 1000.0 if ttft is not None else None
        res.content_chars = content_chars
        res.model_echoed = seen_model

        if usage_payload:
            res.usage = parse_usage(self.ep.protocol, usage_payload)
            res.completion_tokens = res.usage.output_tokens
        if error_text:
            res.error = f"stream error: {error_text}"
            return
        if content_chars == 0 and usage_payload is None:
            res.error = "stream produced no content and no usage"
            return
        res.ok = True


def _extract_delta(protocol: str, payload: dict) -> str:
    if protocol == "anthropic":
        if payload.get("type") == "content_block_delta":
            return (payload.get("delta") or {}).get("text") or ""
        if payload.get("type") == "message_start":
            return ""
        return ""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    return delta.get("content") or ""
