# Published snapshots

Every file here is the verbatim output of a `relay-audit catalog` run. Nothing is
hand-edited. If a number appears in a published comparison table, the raw JSON
behind it is in this directory.

| File | Run date | What it contains |
|---|---|---|
| `catalog-2026-09-22.json` | 2026-09-22 | Raw collected data: every provider, every model, every price, the probe log, and the exchange rate used |
| `catalog-2026-09-22.md` | 2026-09-22 | The rendered table for that same run |

## How to reproduce

```bash
python -m relay_audit catalog --out results/repro --fx 7.1
```

Then compare your `results/repro/catalog.json` with the snapshot here.

- **Request bodies, model lists and prices should match.** If they do not, either
  a provider changed its published prices, or this repository is wrong. Either
  way, open an issue: a divergence is data.
- **Timestamps will not match.** That is expected.

## Rules these snapshots follow

1. **No value is ever inferred.** A provider that does not publish a price shows
   `未采集到`. One invented figure would invalidate the whole table, because the
   table's only value is that every cell traces to a source.
2. **The currency is declared, never guessed.** A CNY figure read as USD is wrong
   by the exchange rate. During development this exact mistake turned a 1.06x
   markup into an apparent 7.50x markup.
3. **Multi-route models disclose the spread.** Where a provider exposes several
   upstream routes at different prices, the table shows the route count and the
   range rather than quietly reporting the cheapest one.
4. **Unmatched models are listed, not dropped.** Anything a provider offers that
   is not in `models.toml` is reported as unmatched, so coverage gaps stay visible.
5. **The vantage point and collection time are recorded.** Prices expire. A table
   without its collection date is a rumour.

## Declared interest

The maintainer of this repository also operates one of the endpoints that appears
in these snapshots, as the `candidate` role. That endpoint's rows are included
including the models where it is more expensive than the reference. Readers
should weigh the results accordingly, and re-run the collector rather than
trusting this directory.
