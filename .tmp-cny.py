import json

d = json.load(open("results/catalog-cny/catalog.json", encoding="utf-8"))
fx = d["fx"]["usd_cny"]

off, site = {}, {}
for p in d["providers"]:
    tgt = off if "relay-api" not in p["base_url"] else site
    for m in p["models"]:
        if m["input_usd_per_mtok"]:
            tgt[m["canonical"]] = m

print("汇率 %.2f\n" % fx)
hdr = "%-22s %16s %16s %8s %8s" % ("model", "official CNY/M", "site CNY/M", "in-fold", "out-fold")
print(hdr)
print("-" * len(hdr))
rows = []
for k, m in site.items():
    o = off.get(k)
    if not o:
        continue
    oi, oo = o["input_usd_per_mtok"] * fx, o["output_usd_per_mtok"] * fx
    si, so = m["input_usd_per_mtok"] * fx, m["output_usd_per_mtok"] * fx
    fi, fo = si / oi, so / oo
    rows.append((k, oi, oo, si, so, fi, fo, m.get("route_count", 1)))
rows.sort(key=lambda r: r[5])
for k, oi, oo, si, so, fi, fo, rc in rows:
    print("%-22s %7.1f /%-7.1f %7.1f /%-7.1f %7.2fx %7.2fx  (%d route)" % (k, oi, oo, si, so, fi, fo, rc))

print()
print("cheaper than official on input :", sum(1 for r in rows if r[5] < 1.0), "/", len(rows))
print("cheaper than official on output:", sum(1 for r in rows if r[6] < 1.0), "/", len(rows))
print()
print("most expensive relative to official:")
for r in sorted(rows, key=lambda x: -x[6])[:3]:
    print("   %-22s output %.2fx" % (r[0], r[6]))
