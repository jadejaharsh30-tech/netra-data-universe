"""One-off: turn the starter-data CSVs into series JSON so every dataset has a snapshot before agents run."""
import sys, pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workers.common import write_series, registry
from workers import valuation
src = Path(sys.argv[1])
own = {d: a["id"] for a in registry().values() for d in a.get("datasets", [])}
titles = {"market_structure_signals_monthly": "Market structure — size, style and sector ratios", "us_debt_stack_quarterly": "US debt stack — quarterly",
          "us_rates_liquidity_monthly": "US rates, credit spreads and liquidity", "gold_silver_fair_value_monthly": "Gold & silver fair value (money-supply model)",
          "nifty_below_200dma_streaks": "Nifty 50 — longest stretches below the 200-DMA", "nifty_negative_month_streaks": "Nifty 50 — runs of negative months",
          "nifty_negative_week_streaks": "Nifty 50 — runs of negative weeks", "fpi_flows_monthly": "FPI net investment — monthly (NSDL)",
          "rupee_rates_inflation_monthly": "Rupee, REER, India–US rates and real rates — monthly", "em_reer_bis_monthly": "EM real effective exchange rates (BIS)",
          "em_fx_volatility": "EM FX: typical annual move vs USD", "india_co_eps_yearly": "India Co. EPS — Nifty 50, CY and FY",
          "india_co_valuations_monthly": "India Co. valuations — 24 Nifty indices, month-end"}
for f in sorted(src.glob("*.csv")):
    df = pd.read_csv(f)
    df = df[[c for c in df.columns if not c.startswith("tri") and c not in ("nifty_close",)]]
    sid = f.stem
    freq = "Q" if "quarterly" in sid else "M" if "monthly" in sid else "A"
    print(sid, write_series(sid, df, own.get(sid, "unassigned"), titles.get(sid, sid), freq, "Starter snapshot (25-Nov-2026)"))
st = pd.read_csv(valuation.STORE / "valuation_daily.csv")
g = pd.read_csv(valuation.STORE / "fred" / "INDIRLTLT01STM.csv", parse_dates=["observation_date"]).set_index("observation_date").iloc[:, 0]
g.index = g.index.to_period("M")
val, ye, snap, splice, lastd = valuation.compute(st, g.groupby(level=0).last())
write_series("india_co_valuations_monthly", val, "valuation", titles["india_co_valuations_monthly"], "M", "EPS = close / P/E. NSE moved P/E from standalone to consolidated earnings on 31-Mar-2021.")
write_series("india_co_eps_yearly", ye, "valuation", titles["india_co_eps_yearly"], "A", f"Pre-Mar-2021 EPS multiplied by {splice:.4f} so growth is on a consolidated basis throughout.")
write_series("valuation_snapshot", snap, "valuation", "Valuation snapshot — latest trading day", "D", f"As of {lastd:%d-%b-%Y}")
print("splice", round(splice, 4), "last", lastd)
