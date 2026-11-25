"""Publisher: rebuilds data/catalog.json (304 metrics with owner, live value, freshness) and status/summary.json
(everything the Control Room shows). Every agent runs this before committing."""
import re, sys
from .common import ROOT, DATA, STATUS, rj, wj, now, registry, clean

VAL_IDX = "NIFTY 50"
SKIP = {"month", "quarter", "period", "month_end", "index", "currency", "partial_month"}
WORD = re.compile(r"[a-z0-9]+")
# metric-name prefix -> (column, index) where the automatic match is wrong; column None = keep the text reading
OVERRIDE = {
    "India Co. EPS — long-run": (None, None), "Midcap 150 / Smallcap 250": ("pe", "NIFTY MIDCAP 150"),
    "Nifty P/B relative to midcaps": ("nifty_pb_rel_midcap150_pct", None), "Nifty Top 10 EW: P/E": ("pe_pctile_full_hist", "NIFTY TOP 10 EQUAL WEIGHT"),
    "Banks: Bank Nifty P/B": ("pb", "NIFTY BANK"), "Private bank P/B premium": (None, None), "FPI net equity flows": ("eq_usd_bn_roll12m", None),
    "Nifty consecutive trading days below": (None, None), "Starting 5Y-return decile": (None, None),
    "Top 10 EW TRI / Nifty 500": ("top10ew_vs_nifty500_ratio_pctile", None), "Sector base-rate score": (None, None),
    "Gold returns vs local equity": (None, None), "India–US CPI inflation differential": ("india_us_inflation_diff_pp", None),
    "USD/INR YoY": ("usdinr_yoy_pct", None), "IT: Nifty IT P/E": ("pe", "NIFTY IT"), "Pharma:": ("pe", "NIFTY PHARMA"),
    "US total credit to non-financial": ("total_nonfin_credit_pct_gdp_bis", None), "US federal interest payments": ("federal_interest_pct_gdp", None),
    "US fiscal deficit (3M avg)": ("fed_bs_12m_change_usd_bn", None), "US high-yield OAS": ("us_hy_oas_pct", None),
    "US M2 growth": ("us_m2_yoy_pct", None), "Gold fair value": ("gold_fair_midpoint", None), "Crude oil price": ("brent_usd_bbl_wb", None),
    "Private banks: loan growth": ("implied_roe_pct", "NIFTY PRIVATE BANK"),
}


def override(metric):
    for k, v in OVERRIDE.items():
        if metric.startswith(k):
            return v
    return False


def slug(s):
    return "-".join(WORD.findall(s.lower()))[:70]


def owner_of(sec_code, dataset, reg):
    for a in reg.values():
        if dataset and dataset in a.get("datasets", []):
            return a["id"]
    for a in reg.values():
        if sec_code in a.get("sections", []):
            return a["id"]
    return None


def pick_column(entry, cols):
    built = entry.get("built") or ""
    for part in re.split(r"[;,]", built.split(":", 1)[1] if ":" in built else built):
        c = part.strip().split(" ")[0]
        if c in cols:
            return c
    toks = set(WORD.findall((entry["metric"]).lower())) - {"nifty", "india", "co", "the", "of", "vs", "and", "in", "to"}
    best, score = None, 0
    for c in cols:
        if c in SKIP:
            continue
        ct = set(c.split("_"))
        sc = len(toks & ct) + (0.5 if ("pctile" in ct) == ("percentile" in toks or "pctile" in toks) else 0)
        if sc > score:
            best, score = c, sc
    return best if score >= 1.5 else None


def fmt(v, col):
    if v is None:
        return "—"
    if "usd_bn" in col and "pct" not in col:
        return (("-" if v < 0 else "+") + f"${abs(v):,.1f}bn") if "roll" in col or "change" in col else f"${v:,.0f}bn"
    if "pct_gdp" in col:
        return f"{v:.1f}% of GDP"
    if col.endswith("_pct") or col.endswith("_pp"):
        return f"{v:+.1f}{'%' if col.endswith('_pct') else ' pp'}" if any(w in col for w in ("yoy", "change", "growth", "cagr", "rel_", "premium", "drawdown")) or any(w in col for w in ("spread", "diff", "erp")) else f"{v:.1f}{'%' if col.endswith('_pct') else ' pp'}"
    if "pctile" in col:
        n = round(v); suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suf} pctile"
    if col in ("pe", "pb") or col.endswith("_ratio") or col.startswith("beer"):
        return f"{v:.2f}x"
    return f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}"


def latest(series, col, idx):
    ci = series["columns"].index(col)
    ii = series["columns"].index("index") if "index" in series["columns"] else None
    for r in reversed(series["rows"]):
        if ii is not None and r[ii] != idx:
            continue
        if r[ci] is not None:
            return r[ci], r[0]
    return None, None


KPIS = [  # id, label, dataset, column, index, sub-column, unit
    ("eps", "India Co. EPS", "india_co_valuations_monthly", "eps", "NIFTY 50", "eps_yoy_pct", "₹"),
    ("pe", "India Co. P/E", "india_co_valuations_monthly", "pe", "NIFTY 50", "pe_pctile_full_hist", "x"),
    ("roe", "India Co. ROE", "india_co_valuations_monthly", "implied_roe_pct", "NIFTY 50", None, "%"),
    ("fpi", "FPI equity, 12M", "fpi_flows_monthly", "eq_usd_bn_roll12m", None, "roll12m_pctile", "$bn"),
    ("reer", "Rupee REER", "rupee_rates_inflation_monthly", "india_reer_bis_broad", None, "reer_pctile_since_1994", ""),
    ("usdinr", "USD/INR", "rupee_rates_inflation_monthly", "usdinr_month_end", None, "usdinr_yoy_pct", "₹"),
]


def headline(reg):
    out = []
    for kid, label, ds, col, idx, sub, unit in KPIS:
        ser = rj(DATA / "series" / f"{ds}.json")
        if not ser:
            continue
        c = ser["columns"]
        if col not in c:
            col = {"usdinr_month_end": "usdinr_monthly_avg"}.get(col, col)
            if col not in c:
                continue
        ci = c.index(col); si = c.index(sub) if sub else None; ii = c.index("index") if "index" in c else None
        pts = [[r[0], r[ci], r[si] if si is not None else None] for r in ser["rows"] if (ii is None or r[ii] == idx) and r[ci] is not None]
        if "partial_month" in c:
            pi = c.index("partial_month"); full = {r[0] for r in ser["rows"] if not r[pi]}
            pts = [p for p in pts if p[0] in full]
        out.append({"id": kid, "label": label, "dataset": ds, "column": col, "sub": sub, "unit": unit, "agent": ser["agent"],
                    "updated": ser["updated"], "points": pts})
    eps = rj(DATA / "series" / "india_co_eps_yearly.json")
    snap = rj(DATA / "series" / "valuation_snapshot.json")
    wj(DATA / "headline.json", {"updated": now(), "kpis": out, "eps_yearly": eps, "snapshot": snap})


def build():
    reg = registry()
    seed = rj(ROOT / "agents" / "catalog_seed.json")
    statuses = {a: rj(STATUS / "agents" / f"{a}.json", {"id": a, "state": "planned" if reg[a]["phase"] == "planned" else "pending"}) for a in reg}
    cache, out = {}, []
    for e in seed:
        sec_code = e["sec"][:2]
        m = re.search(r"([a-z0-9_]+)\.csv", e.get("built") or "")
        ds = m.group(1) if m else ("india_co_valuations_monthly" if (e.get("built") or "").split(":")[0].strip() in
                                    ("pb", "div_yield_pct", "erp_ey_minus_10y_pct", "beer_10y_over_ey") or (e.get("built") or "").startswith("pe_pctile") else None)
        if ds and ds not in cache:
            cache[ds] = rj(DATA / "series" / f"{ds}.json")
        ser = cache.get(ds) if ds else None
        owner = owner_of(sec_code, ds, reg)
        rec = {"id": slug(e["metric"]), "section": e["sec"], "metric": e["metric"], "definition": e["defn"], "free_source": e["free"],
               "paid_source": e["paid"], "frequency": e["freq"], "history": e["hist"], "gotcha": e["gotcha"], "netra": e.get("netra", ""),
               "netra_count": e.get("n", 0), "also_used_by": e.get("also", ""), "owner": owner, "dataset": ds,
               "latest_text": e["latest"], "as_of": None, "value": None, "column": None}
        if ser:
            idx = VAL_IDX
            mi = re.search(r"\((NIFTY[^)]*)\)", e.get("built") or "")
            if mi and "24" not in mi.group(1):
                idx = mi.group(1)
            ov = override(e["metric"])
            col = pick_column(e, ser["columns"]) if ov is False else ov[0]
            if ov and ov[1]:
                idx = ov[1]
            if col:
                v, per = latest(ser, col, idx)
                if v is not None:
                    pre = (idx + " ") if "index" in ser["columns"] and idx != VAL_IDX else ""
                    rec.update(value=v, as_of=per, column=col, index=idx if "index" in ser["columns"] else None,
                               latest_text=f"{pre}{fmt(v, col)} ({per})")
            rec["series_updated"] = ser.get("updated")
        has = rec["column"] is not None
        live = has and owner and reg[owner]["phase"] == "live" and statuses[owner].get("last_success")
        rec["status"] = "live" if live else ("snapshot" if has else "recipe")
        out.append(rec)
    wj(DATA / "catalog.json", {"updated": now(), "metrics": out})

    runs = {a: (rj(STATUS / "runs" / f"{a}.json", []) or [])[:30] for a in reg}
    counts = {}
    for r in out:
        counts.setdefault(r["owner"] or "unassigned", {"live": 0, "snapshot": 0, "recipe": 0})[r["status"]] += 1
    summary = {"updated": now(), "repo": rj(ROOT / "agents" / "registry.json")["repo"],
               "agents": [{**reg[a], "status": statuses[a], "runs": runs[a], "metrics": counts.get(a, {})} for a in reg],
               "events": sorted((e for f in (DATA / "events").glob("*.json") for e in (rj(f, []) or [])), key=lambda e: e["t"], reverse=True)[:60],
               "totals": {k: sum(c[k] for c in counts.values()) for k in ("live", "snapshot", "recipe")}}
    wj(STATUS / "summary.json", summary, 1)
    headline(reg)
    print("catalog:", summary["totals"], "| mapped:", sum(1 for r in out if r["column"]))


if __name__ == "__main__":
    build()
