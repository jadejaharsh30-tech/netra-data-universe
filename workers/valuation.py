"""Valuation agent: India Co. P/E, P/B, dividend yield, EPS, ROE for 24 Nifty indices.
Source: NSE daily 'all indices close' file (nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv)."""
import io, sys
from datetime import date, datetime, timedelta
import numpy as np, pandas as pd
from .common import STORE, IST, run_agent, session, write_series, set_status

AGENT = "valuation"
URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d}.csv"
MAX_DAYS = 45  # days back-filled per run


def key(n):
    return n.upper().replace(" ", "")


def fetch_new(store):
    names = {key(n): n for n in store["index"].unique()}
    last = pd.to_datetime(store["date"]).max().date()
    today = datetime.now(IST).date()
    s = session(); s.headers["Referer"] = "https://www.nseindia.com/"
    rows, tried, got, d = [], 0, [], last + timedelta(days=1)
    while d <= today and tried < MAX_DAYS:
        if d.weekday() < 5:
            tried += 1
            set_status(AGENT, task=f"Fetching NSE close file for {d:%d-%b-%Y}")
            r = s.get(URL.format(d=d.strftime("%d%m%Y")), timeout=30)
            if r.status_code == 200 and r.text.startswith("Index Name"):
                f = pd.read_csv(io.StringIO(r.text))
                f["k"] = f["Index Name"].map(key)
                f = f[f["k"].isin(names)]
                for _, x in f.iterrows():
                    rows.append({"date": d.isoformat(), "index": names[x["k"]], "close": x["Closing Index Value"],
                                 "pe": pd.to_numeric(x["P/E"], errors="coerce"), "pb": pd.to_numeric(x["P/B"], errors="coerce"),
                                 "dy": pd.to_numeric(x["Div Yield"], errors="coerce")})
                got.append(d)
            elif r.status_code not in (404, 403):
                r.raise_for_status()
            elif r.status_code == 403:
                raise RuntimeError("NSE archive refused the request (HTTP 403) — runner IP likely blocked")
        d += timedelta(days=1)
    if tried == 0:  # nothing new to fetch: still prove the source answers us
        set_status(AGENT, task="Checking the NSE archive responds")
        r = s.get(URL.format(d=last.strftime("%d%m%Y")), timeout=30)
        if r.status_code == 403:
            raise RuntimeError("NSE archive refused the request (HTTP 403) — runner IP likely blocked")
    return pd.DataFrame(rows), got


def compute(store, gsec):
    nv = store.copy(); nv["date"] = pd.to_datetime(nv["date"])
    nv["ym"] = nv["date"].dt.to_period("M")
    me = nv.sort_values("date").groupby(["index", "ym"]).last().reset_index()
    out = []
    for idx, g in me.groupby("index"):
        g = g.set_index("ym").sort_index()
        o = pd.DataFrame(index=g.index)
        o["index"] = idx; o["close"] = g["close"]; o["pe"] = g["pe"]; o["pb"] = g["pb"]; o["div_yield_pct"] = g["dy"]
        o["eps"] = g["close"] / g["pe"]; o["bvps"] = g["close"] / g["pb"]
        o["implied_roe_pct"] = g["pb"] / g["pe"] * 100; o["earnings_yield_pct"] = 100 / g["pe"]
        o["eps_yoy_pct"] = (o["eps"] / o["eps"].shift(12) - 1) * 100
        o["eps_5y_cagr_pct"] = ((o["eps"] / o["eps"].shift(60)) ** 0.2 - 1) * 100
        o["pe_pctile_full_hist"] = o["pe"].expanding(24).apply(lambda x: (x[:-1] < x[-1]).mean() * 100, raw=True)
        mu, sd = o["pe"].expanding(24).mean(), o["pe"].expanding(24).std()
        o["pe_zscore_expanding"] = (o["pe"] - mu) / sd
        o["pe_10y_rolling_avg"] = o["pe"].rolling(120, min_periods=60).mean()
        o["pe_10y_median"] = o["pe"].rolling(120, min_periods=60).median()  # robust to loss-year P/E spikes
        o["india_10y_gsec_pct"] = gsec.reindex(o.index)
        o["erp_ey_minus_10y_pct"] = o["earnings_yield_pct"] - o["india_10y_gsec_pct"]
        o["beer_10y_over_ey"] = o["india_10y_gsec_pct"] / o["earnings_yield_pct"]
        out.append(o)
    val = pd.concat(out).rename_axis("month").reset_index()
    val["month"] = val["month"].astype(str)
    cols = ["month"] + [c for c in val.columns if c != "month"]
    val = val[cols]

    # Yearly India Co. EPS with the 31-Mar-2021 standalone -> consolidated splice
    n50 = nv[nv["index"] == "NIFTY 50"].set_index("date").sort_index()
    splice = n50.loc[:"2021-03-30", "pe"].iloc[-1] / n50.loc["2021-03-31", "pe"]
    m = val[val["index"] == "NIFTY 50"].set_index("month")
    epsc = m["eps"].where(pd.PeriodIndex(m.index, freq="M") >= pd.Period("2021-03", "M"), m["eps"] * splice)
    yr = []
    for y in range(2000, datetime.now(IST).year + 1):
        for lbl, mm in (("CY", 12), ("FY", 3)):
            k = f"{y}-{mm:02d}"
            if k in m.index:
                yr.append({"period": f"CY{y}" if lbl == "CY" else f"FY{str(y)[2:]}", "month_end": k, "pe": m.loc[k, "pe"],
                           "pb": m.loc[k, "pb"], "eps_as_published": m.loc[k, "eps"], "eps_consolidated_basis": epsc[k],
                           "implied_roe_pct": m.loc[k, "implied_roe_pct"]})
    ye = pd.DataFrame(yr)
    for lbl in ("CY", "FY"):
        sel = ye["period"].str.startswith(lbl)
        ye.loc[sel, "eps_growth_pct"] = ye.loc[sel, "eps_consolidated_basis"].pct_change() * 100
    last = m.iloc[-1]
    ye = pd.concat([ye, pd.DataFrame([{"period": "Latest", "month_end": m.index[-1], "pe": last["pe"], "pb": last["pb"],
                                      "eps_as_published": last["eps"], "eps_consolidated_basis": epsc.iloc[-1],
                                      "implied_roe_pct": last["implied_roe_pct"]}])], ignore_index=True)
    ye = ye[["period", "month_end", "pe", "pb", "eps_as_published", "eps_consolidated_basis", "eps_growth_pct", "implied_roe_pct"]]

    # Latest daily snapshot, 24 indices
    lastd = nv["date"].max()
    snap = nv[nv["date"] == lastd][["index", "pe", "pb", "dy"]].merge(
        val.groupby("index").last()[["pe_pctile_full_hist", "pe_10y_median", "eps_yoy_pct", "implied_roe_pct"]].reset_index(), on="index")
    snap = snap.sort_values("index")
    return val, ye, snap, splice, lastd


def main():
    p = STORE / "valuation_daily.csv"
    store = pd.read_csv(p)
    prev = pd.to_datetime(store["date"]).max()
    new, got = fetch_new(store)
    warnings = []
    if len(new):
        store = pd.concat([store, new]).drop_duplicates(["date", "index"], keep="last").sort_values(["date", "index"])
        store.to_csv(p, index=False)
        n_idx = new["index"].nunique()
        if n_idx < 24:
            warnings.append(f"Only {n_idx}/24 indices found in the latest NSE file — check index name changes")
    g = pd.read_csv(STORE / "fred" / "INDIRLTLT01STM.csv", parse_dates=["observation_date"]).set_index("observation_date").iloc[:, 0]
    g.index = g.index.to_period("M")
    val, ye, snap, splice, lastd = compute(store, g.groupby(level=0).last())
    set_status(AGENT, task="Writing India Co. series")
    write_series("india_co_valuations_monthly", val, AGENT, "India Co. valuations — 24 Nifty indices, month-end", "M",
                 "EPS = close / P/E. NSE moved P/E from standalone to consolidated earnings on 31-Mar-2021.")
    write_series("india_co_eps_yearly", ye, AGENT, "India Co. EPS — Nifty 50, CY and FY", "A",
                 f"Pre-Mar-2021 EPS multiplied by {splice:.4f} so growth is on a consolidated basis throughout.")
    write_series("valuation_snapshot", snap, AGENT, "Valuation snapshot — latest trading day", "D", f"As of {lastd:%d-%b-%Y}. 10Y figure is a median: NSE's P/E spikes when index earnings collapse (Smallcap 250 in 2016, Realty and Auto in 2020–21).")
    n50 = val[val["index"] == "NIFTY 50"].iloc[-1]
    ev = []
    if got:
        ev.append({"kind": "data", "text": f"{len(got)} new trading day(s) to {got[-1]:%d-%b}. Nifty 50 P/E {n50['pe']:.2f}x "
                                           f"(pctile {n50['pe_pctile_full_hist']:.0f}), EPS {n50['eps']:.0f}, ROE {n50['implied_roe_pct']:.1f}%"})
        if (got[-1].year, got[-1].month) != (prev.year, prev.month):
            ev.append({"kind": "month", "text": f"New month started: India Co. EPS YoY {n50['eps_yoy_pct']:+.1f}%"})
    return {"rows": len(new), "message": f"{len(got)} new day(s); data through {lastd:%d-%b-%Y}" if got else
            f"No new NSE file yet; data through {lastd:%d-%b-%Y}", "data_through": f"{lastd:%Y-%m-%d}",
            "events": ev, "warnings": warnings}


if __name__ == "__main__":
    sys.exit(run_agent(AGENT, main))
