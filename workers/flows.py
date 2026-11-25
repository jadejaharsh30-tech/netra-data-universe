"""Flows agent: FPI net investment, monthly, from NSDL (fpi.nsdl.co.in Yearwise report, INR and USD)."""
import io, sys
from datetime import datetime
import pandas as pd
from bs4 import BeautifulSoup
from .common import STORE, IST, run_agent, session, write_series, set_status

AGENT = "flows"
URL = "https://www.fpi.nsdl.co.in/web/Reports/Yearwise.aspx?RptType=6"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def year_table(s, year, cur):
    soup = BeautifulSoup(s.get(URL, timeout=40).text, "lxml")
    form = {i.get("name"): i.get("value", "") for i in soup.select("input[type=hidden]") if i.get("name")}
    form.update({"__EVENTTARGET": "ddl", "__EVENTARGUMENT": "", "ddl": str(year), "hdnCurr": cur})
    html = s.post(URL, data=form, timeout=60, headers={"Referer": URL}).text
    soup = BeautifulSoup(html, "lxml")
    out, upto = {}, None
    for tr in soup.select("table tr"):
        c = [td.get_text(strip=True).replace(",", "") for td in tr.find_all(["td", "th"])]
        if c and c[0] in MONTHS and len(c) >= 3:
            try:
                out[f"{year}{MONTHS.index(c[0]) + 1:02d}"] = (float(c[1]), float(c[-1]))  # (equity, total)
            except ValueError:
                pass
        if c and "up to" in c[0].lower():
            upto = c[0].strip("* ")
    if not out:
        raise RuntimeError(f"NSDL {year} {cur}: no monthly rows parsed — page layout may have changed")
    return out, upto


def main():
    p = STORE / "fpi_monthly.csv"
    st = pd.read_csv(p, dtype={"yyyymm": str}).set_index("yyyymm")
    before = st.copy()
    s = session()
    today = datetime.now(IST)
    years = [today.year - 1, today.year] if today.month <= 2 else [today.year]
    upto = None
    for y in years:
        set_status(AGENT, task=f"Reading NSDL FPI report {y} (USD)")
        usd, upto = year_table(s, y, "USD")
        set_status(AGENT, task=f"Reading NSDL FPI report {y} (INR)")
        inr, _ = year_table(s, y, "INR")
        for k, (eq, tot) in usd.items():
            st.loc[k, ["eq_usd_mn", "total_usd_mn"]] = [eq, tot]
            if k in inr:
                st.loc[k, "eq_inr_cr"] = inr[k][0]
    st = st.sort_index()
    st.reset_index().to_csv(p, index=False)
    changed = int((st.reindex(before.index).ne(before).any(axis=1)).sum() + len(st.index.difference(before.index)))

    f = st.copy()
    f.index = pd.PeriodIndex([f"{k[:4]}-{k[4:]}" for k in f.index], freq="M")
    for w in (3, 12, 24):
        f[f"eq_usd_bn_roll{w}m"] = f["eq_usd_mn"].rolling(w).sum() / 1000
    for w in (12, 24):
        x = f[f"eq_usd_bn_roll{w}m"]
        f[f"roll{w}m_zscore"] = (x - x.mean()) / x.std()
        f[f"roll{w}m_pctile"] = x.rank(pct=True) * 100
    f["partial_month"] = 0
    cur = pd.Period(today.strftime("%Y-%m"), "M")
    if cur in f.index:
        f.loc[cur, "partial_month"] = 1
    f = f.rename_axis("month").reset_index(); f["month"] = f["month"].astype(str)
    write_series("fpi_flows_monthly", f, AGENT, "FPI net investment — monthly (NSDL)", "M",
                 f"Latest month is partial ({upto}). Equity = secondary + primary market." if upto else "")
    full = f[f["partial_month"] == 0].iloc[-1]
    last = f.iloc[-1]
    ev = []
    if changed:
        ev.append({"kind": "data", "text": f"FPI equity {last['month']} so far ${last['eq_usd_mn'] / 1000:+.2f}bn; "
                                           f"12M rolling ${full['eq_usd_bn_roll12m']:+.1f}bn (pctile {full['roll12m_pctile']:.0f})"})
    if full["roll12m_pctile"] <= 5:
        ev.append({"kind": "extreme", "text": f"12M FPI equity outflow in bottom 5% of history ({full['month']})"})
    return {"rows": changed, "message": f"{changed} month(s) updated; {upto or ''}".strip("; "), "data_through": last["month"], "events": ev}


if __name__ == "__main__":
    sys.exit(run_agent(AGENT, main))
