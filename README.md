# relay-audit

**A reproducible audit tool for LLM API relays / proxies: cache honesty, billing honesty, latency and cost.**

Most relay benchmarks only measure speed. Speed is the least interesting number — a relay can be fast and still silently eat your tokens, fake prompt-cache hits, or bill you for failed requests.

`relay-audit` measures the things you can actually verify, and it publishes its own methodology so anyone can re-run it and get the same numbers.

**→ [`data/published/`](data/published/) holds the raw collected data behind every published price table.** Nothing there is hand-edited.

> **Declared interest.** The maintainer of this repository also operates one of the endpoints that appears in the published snapshots, under the `candidate` role. That endpoint's rows are included *including* the models where it is more expensive than the reference. Re-run the collector rather than trusting the snapshot.

```
                       same request body, same model, one runner
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                               ▼
  reference                       candidate                          peer
  (OpenRouter)                    (under audit)                      (real, paid)
        │                               │                               │
        └───────────────────────────────┼───────────────────────────────┘
                                        ▼
                    ┌───────────────────────────────────────┐
                    │  speed    TTFT p50/p90/p99, tps,      │
                    │           failure count               │
                    │  cache    cold → warm ×N → after TTL  │
                    │  billing  token reconciliation,       │
                    │           impossible-request probes   │
                    └───────────────────┬───────────────────┘
                                        ▼
                    ┌───────────────────────────────────────┐
                    │ cache verdict requires TWO signals    │
                    │                                       │
                    │  declared  cache_read > 0 on warm     │
                    │  physical  warm TTFT < cold TTFT      │
                    │                                       │
                    │  both agree      → consistent         │
                    │  counter only    → counter-only  ⚠    │
                    │  speed only      → speed-only         │
                    │  neither         → no-cache           │
                    └───────────────────┬───────────────────┘
                                        ▼
              raw.json · findings.json · env.json · report.md
```

---

## Why this exists

Relay (中转) providers are opaque. You cannot see their upstream. But you *can* verify a few things that a dishonest relay cannot fake simultaneously:

| Question | How it is verified | Cheap fake that fails |
|---|---|---|
| Are cache hits real? | `cache_read_input_tokens` **plus** a wall-clock TTFT drop on the warm pass | Returning a nonzero `cache_read` counter while TTFT stays flat |
| Are tokens counted honestly? | Compare reported `usage` against independently tokenized input | Inflating `prompt_tokens` |
| Do failed requests get billed? | Send a request that must fail, then reconcile | Silent billing on 4xx/5xx |
| Is the model the real one? | Record the echoed model id on every response | Silent channel substitution |
| What is the effective markup? | Reported usage × configured rate ÷ published official rate | Hiding markup behind opaque "credits" |

The right-hand column is the whole point: **for every test, this tool documents what a dishonest provider would have to do to fake it, and how the test catches that.**

---

## Status

- [x] Config + multi-endpoint adapter (OpenAI-compatible and Anthropic-native)
- [x] TTFT / throughput measurement
- [x] Cache honesty test (cold → warm → cold, TTFT cross-check)
- [x] Billing honesty test (token reconciliation, failed-request probe, model identity)
- [x] Cost accounting + JSON/Markdown report
- [ ] Multi-region runners
- [ ] Community submitted results

---

## Install

```bash
git clone <this repo>
cd relay-audit
python -m venv .venv
# Windows: .venv\Scripts\activate
. .venv/bin/activate
pip install -e .
```

Requires Python 3.10+. Only runtime dependency is `httpx`.

## Configure

```bash
cp .env.example .env
```

```ini
RELAY_A_KEY=sk-...
OPENROUTER_KEY=sk-or-...
PEER_KEY=sk-...
```

Then edit `config.toml`. `role` matters: the report always lists the `reference` first and never hides the candidate's losses.

```toml
[[endpoint]]
id = "openrouter"
label = "OpenRouter"
protocol = "openai"
base_url = "https://openrouter.ai/api/v1"
key_env = "OPENROUTER_KEY"
model = "anthropic/claude-sonnet-5"
role = "reference"

[[endpoint]]
id = "candidate"
label = "My Relay"
protocol = "openai"
base_url = "https://example.com/v1"
key_env = "RELAY_A_KEY"
model = "claude-sonnet-5"
role = "candidate"

[[endpoint]]
id = "peer"
label = "Peer Relay"
protocol = "openai"
base_url = "https://peer.example/v1"
key_env = "PEER_KEY"
model = "claude-sonnet-5"
role = "peer"
```

`reference` should be a first-party or publicly benchmarked endpoint. OpenRouter is the default choice because it publishes routing and pricing.

## Run

```bash
# free: validates config, prints the request plan and estimated spend
python -m relay_audit plan

# full audit
python -m relay_audit run --out results/2026-09-15

# single suite
python -m relay_audit run --only cache
python -m relay_audit run --only billing
```

Every run writes:

```
results/<date>/
  raw.json        # every request verbatim: status, headers, usage, timings
  report.md       # human-readable tables
  env.json        # tool version, host, egress country, timestamp, model ids
```

**`env.json` is not optional.** A latency number without its vantage point is not a measurement.

---

## `catalog`: published price comparison

Separate from the audit. `catalog` collects what each provider *publishes* about its prices, normalises the currencies and model names, and renders a comparison table.

```bash
# see what each provider publishes, and exactly how it was probed
python -m relay_audit catalog --out results/catalog --fx 7.1

# dump a raw sample of each /models payload, for writing manual [[rates]] blocks
python -m relay_audit catalog --probe
```

Three rules make the output trustworthy:

1. **A price is never inferred.** A provider that publishes no prices yields `未采集到`. One invented figure would invalidate the whole table, because the table's only value is that every cell traces to a source.
2. **The currency is declared, not guessed.** `currency = "CNY"` in `config.toml`. Reading a CNY figure as USD is wrong by the exchange rate — during development this produced a 7.50× markup on a service whose real markup was 1.06×. The tool did not silently guess; it reported the configured value.
3. **Multi-route models disclose the spread.** A relay may expose several upstream routes at different prices, where the top-level figure is merely the cheapest. The table shows the route count and the input/output range rather than quietly reporting the best-looking number.

For providers that only show prices inside a logged-in dashboard, declare them by hand. The block is deliberately verbose so that a published table can be traced back to a person, a date and a source:

```toml
[[rates]]
endpoint = "peer"
model = "claude-sonnet-5"
input = 2.20
output = 11.00
currency = "USD"
retrieved = "2026-09-15"
note = "价格取自登录后控制台"
```

### Comparison against the official baseline

`catalog` compares each provider's price against a reference rate declared in `models.toml`. Two things matter here:

- **The reference must be sourced and dated.** Every entry carries `source` and `retrieved`. An entry without both is flagged, and an entry with no `official_*` values produces an explicit "cannot compute a markup multiple" note instead of a fabricated baseline.
- **Pick the baseline deliberately.** Third-party relays often publish per-route pricing for their own upstream channels, which is not the same thing as the vendor's list price. Decide which baseline you are comparing against, and state it in the document you publish — a table that silently switches baselines between rows is misleading even when every individual number is correct.

---

## Test design

### 1. Speed (`--only speed`)

- Streaming `chat/completions`, `max_tokens=8`, fixed prompt.
- `n=15` after 2 warm-up requests (warm-ups discarded).
- Records the TLS handshake separately, so a slow CDN cannot masquerade as slow inference.
- Records time to first content delta, time to last delta, completion tokens, tokens/sec.
- Reports p50 / p90 / p99 **and the failure count, not only the successes**.

### 2. Cache honesty (`--only cache`)

This is the test worth running:

```
run A: long unique prefix, cold         -> expect cache_write > 0, cache_read == 0
run B: byte-identical prefix, immediate -> expect cache_read > 0 AND TTFT_B << TTFT_A
run C: wait past the cache TTL          -> expect cache_read == 0 again
```

Two independent signals must agree:

1. **Declared** — `usage.prompt_tokens_details.cached_tokens` (OpenAI shape) or `usage.cache_read_input_tokens` (Anthropic shape).
2. **Physical** — TTFT on the warm pass. A real cache hit skips prefill, so with a multi-thousand-token prefix the warm TTFT should collapse.

If the counter reports hits but TTFT does not move, the counter is decorative. That is the specific failure this suite exists to catch.

| endpoint | declared hit | TTFT cold | TTFT warm | TTFT ratio | verdict |
|---|---|---|---|---|---|

Verdicts: `consistent`, `counter-only` (declares hits, no speedup), `speed-only` (speeds up without declaring), `no-cache`.

Cross-checking both signals is deliberately hard to fake: faking the counter is trivial, faking the speedup costs real money, and paying for a real cache while reporting zero hits merely leaves money on the table.

### 3. Billing honesty (`--only billing`)

- **Token reconciliation** — a prompt of known content is tokenized locally and compared against the reported `prompt_tokens`. Drift is reported with an explicit tolerance rather than a pass/fail, because tokenizers differ.
- **Failed-request billing** — a request that must fail (invalid model id, then an over-limit `max_tokens`). If a provider charges for failures, the cost model will not reconcile against the dashboard.
- **Model identity** — the `model` field echoed back is recorded on every response. Silent channel substitution shows up as a mismatch against the requested model.

### 4. Cost (`--only cost`)

Effective cost per million tokens, derived from **actual reported usage** rather than marketing pages:

```
effective_input = sum(input_tokens) / 1e6 * configured_rate.input
markup_ratio    = configured_rate.input / official_rate.input
```

Official rates are pinned in `rates.toml` with a `retrieved` date and a source URL. A rate without a source and a date is a rumour.

---

## What this tool cannot tell you

Being explicit about this is the difference between a measurement and a marketing page.

1. **It measures from one vantage point.** Latency from mainland China to a US-routed endpoint is a property of the route, not of the endpoint. Only compare latency between runs from the same runner. Cross-region comparison requires running the suite from multiple runners.
2. **It cannot verify upstream identity.** A relay may forward to the official API or to a pool of subscription accounts. Nothing observable from the client distinguishes those, except that usage shapes and cache semantics tend to differ. Treat the output as *evidence*, not proof.
3. **TTFT is co-tenant dependent.** You share upstream capacity with everyone else on that channel. Run at several times of day; a single window is an anecdote.
4. **`cache_read_input_tokens` is self-reported.** It is the most contested number in the relay ecosystem precisely because it is easy to fake. That is why test 2 requires the physical TTFT signal to agree.
5. **Results expire.** Models, pricing and routing change weekly. Every report carries its timestamp, and the reporter warns when a result is older than 14 days.
6. **Vendor-run results are weak evidence by construction.** This tool is most useful when someone *other than the vendor* runs it. If you are the vendor, publish the raw JSON and expect to be re-tested.

---

## Reproducing a published result

```bash
python -m relay_audit run --out results/repro --seed 20260915
```

`--seed` fixes prompt generation so the cache prefix is byte-identical across runs. Compare your `raw.json` with the published one: request bodies should match, timings will not — that is the point.

Open an issue with a diff if your numbers disagree with a published report. Disagreement is data.

---

## License

MIT
