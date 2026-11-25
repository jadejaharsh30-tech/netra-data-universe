"""External & Rupee agent: USD/INR, BIS REER/NEER (India + EM peers), India-US rates, real rates, EM FX volatility.
Source: FRED (fredgraph.csv, no key). India CPI after FRED's OECD series ends falls back to the frozen TradingView seed."""
import io, os, sys
import numpy as np, pandas as pd
from .common import STORE, run_agent, session, write_series, set_status

AGENT = "external"
SERIES = ["DEXINUS", "EXINUS", "RBINBIS", "NBINBIS", "INDIRLTLT01STM", "GS10", "CPIAUCSL", "DFII10", "INDCPIALLMINMEI",
          "DEXKOUS", "DEXBZUS", "DEXCHUS", "DEXTAUS", "RBCNBIS", "RBKRBIS", "RBTWBIS", "RBBRBIS"]
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
API = "https://api.stlouisfed.org/fred/series/observations?series_id={}&api_key={}&file_type=json&observation_start=2000-01-01"
KEY = os.environ.get("FRED_API_KEY", "").strip()


def pull(s, sid):
    if KEY:  # official API: reliable from cloud runners; free key from fredaccount.stlouisfed.org
        r = s.get(API.format(sid, KEY), timeout=20)
        r.raise_for_status()
        df = pd.DataFrame(r.json()["observations"])[["date", "value"]]
        df.columns = ["observation_date", sid]
        old = pd.read_csv(STORE / "fred" / f"{sid}.csv")
        old = old[old["observation_date"] < df["observation_date"].min()]
        df = pd.concat([old.astype({sid: str}), df.astype({sid: str})])
    else:
        r = s.get(URL.format(sid), timeout=20)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["observation_date", sid]
    df[sid] = pd.to_numeric(df[sid], errors="coerce")
    return df.dropna()


def load(sid):
    s = pd.read_csv(STORE / "fred" / f"{sid}.csv", parse_dates=["observation_date"]).set_index("observation_date").iloc[:, 0]
    return s


def m(s, how="last"):
    s = s.copy(); s.index = s.index.to_period("M")
    return s.groupby(level=0).last() if how == "last" else s.groupby(level=0).mean()


def main():
    s = session(retries=1); rows, fails, latest = 0, [], {}
    for n, sid in enumerate(SERIES):
        set_status(AGENT, task=f"Pulling FRED {sid}" + (" (API)" if KEY else ""))
        try:
            new = pull(s, sid)
        except Exception as e:
            fails.append(f"{sid}: {type(e).__name__}: {str(e)[:120]}")
            print(fails[-1], flush=True)
            if n == 2 and len(fails) == 3:
                raise RuntimeError("FRED not answering from this runner (first 3 series failed). "
                                   + ("" if KEY else "Add a free FRED_API_KEY repo secret to use the official API. ") + fails[0])
            continue
        p = STORE / "fred" / f"{sid}.csv"
        old = pd.read_csv(p) if p.exists() else new.iloc[:0]
        rows += max(0, len(new) - len(old))
        new.to_csv(p, index=False)
        latest[sid] = new["observation_date"].iloc[-1]
    if len(fails) > len(SERIES) // 2:
        raise RuntimeError("FRED unreachable for most series: " + "; ".join(fails[:5]))

    set_status(AGENT, task="Computing rupee, REER and real-rate series")
    tv = pd.read_csv(STORE / "tv_india_seed.csv", parse_dates=["date"])
    tvs = lambda n: tv[tv.series == n].set_index("date")["value"].pipe(lambda x: x.set_axis(x.index.to_period("M")))
    in_cpi = tvs("IN_CPI_YOY_PCT").combine_first(m(load("INDCPIALLMINMEI")).pct_change(12) * 100)
    fx = pd.DataFrame({"india_reer_bis_broad": m(load("RBINBIS")), "india_neer_bis_broad": m(load("NBINBIS")),
                       "usdinr_monthly_avg": m(load("EXINUS")), "usdinr_month_end": m(load("DEXINUS")),
                       "india_cpi_yoy_pct": in_cpi, "us_cpi_yoy_pct": m(load("CPIAUCSL")).pct_change(12) * 100,
                       "india_10y_gsec_pct": m(load("INDIRLTLT01STM")), "us_10y_pct": m(load("GS10")),
                       "us_real_10y_tips_pct": m(load("DFII10"), "mean")})
    fx = fx[fx.index >= pd.Period("1994-01", "M")]
    r = fx["india_reer_bis_broad"]
    fx["reer_vs_avg_since_1994_pct"] = (r / r.expanding().mean() - 1) * 100
    fx["reer_pctile_since_1994"] = r.expanding(12).apply(lambda x: (x[:-1] < x[-1]).mean() * 100, raw=True)
    fx["reer_2y_change_pct"] = (r / r.shift(24) - 1) * 100
    fx["usdinr_yoy_pct"] = (fx["usdinr_monthly_avg"] / fx["usdinr_monthly_avg"].shift(12) - 1) * 100
    fx["india_us_inflation_diff_pp"] = fx["india_cpi_yoy_pct"] - fx["us_cpi_yoy_pct"]
    fx["india_real_10y_pct"] = fx["india_10y_gsec_pct"] - fx["india_cpi_yoy_pct"]
    fx["india_us_10y_spread_pp"] = fx["india_10y_gsec_pct"] - fx["us_10y_pct"]
    fx = fx.dropna(how="all").rename_axis("month").reset_index(); fx["month"] = fx["month"].astype(str)
    write_series("rupee_rates_inflation_monthly", fx, AGENT, "Rupee, REER, India–US rates and real rates — monthly", "M",
                 "REER/NEER: BIS broad, 2020=100. India 10Y: OECD long-term rate via FRED. CPI after 2025 from the TradingView seed until the India Macro agent takes over.")
    reer = pd.DataFrame({k: m(load(v)) for k, v in
                         {"india": "RBINBIS", "china": "RBCNBIS", "korea": "RBKRBIS", "taiwan": "RBTWBIS", "brazil": "RBBRBIS"}.items()})
    reer = reer.rename_axis("month").reset_index(); reer["month"] = reer["month"].astype(str)
    write_series("em_reer_bis_monthly", reer, AGENT, "EM real effective exchange rates (BIS broad, 2020=100)", "M")
    fxd = pd.DataFrame({k: load(v) for k, v in {"INR": "DEXINUS", "KRW": "DEXKOUS", "BRL": "DEXBZUS", "CNY": "DEXCHUS", "TWD": "DEXTAUS"}.items()}).dropna()
    ann = fxd.resample("YE").last().pct_change() * 100
    yrs = (fxd.index[-1] - pd.Timestamp("2010-01-04")).days / 365.25
    vol = pd.DataFrame({"avg_abs_annual_move_since_2014_pct": ann.loc["2014":].abs().mean(),
                        "annualised_daily_vol_since_2014_pct": np.log(fxd.loc["2014":]).diff().std() * np.sqrt(252) * 100,
                        "avg_annual_depreciation_since_2010_pct": ((fxd.iloc[-1] / fxd.loc["2010-01"].iloc[0]) ** (1 / yrs) - 1) * 100})
    vol = vol.rename_axis("currency").reset_index()
    write_series("em_fx_volatility", vol, AGENT, "EM FX: typical annual move vs USD", "A", f"Daily data to {fxd.index[-1]:%d-%b-%Y}")

    last = fx.dropna(subset=["india_reer_bis_broad"]).iloc[-1]
    ev = [{"kind": "data", "text": f"REER {last['india_reer_bis_broad']:.1f} ({last['month']}, pctile {last['reer_pctile_since_1994']:.0f}); "
                                   f"USD/INR {fxd['INR'].iloc[-1]:.2f} on {fxd.index[-1]:%d-%b}"}] if rows else []
    return {"rows": rows, "message": f"{len(SERIES) - len(fails)}/{len(SERIES)} FRED series pulled, {rows} new observations",
            "data_through": f"{fxd.index[-1]:%Y-%m-%d}", "events": ev, "warnings": fails}


if __name__ == "__main__":
    sys.exit(run_agent(AGENT, main))
