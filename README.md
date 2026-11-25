# Netra Data Universe

A live, public map of the macro, earnings and flow numbers behind DSP's **Netra**, plus the agents that keep them fresh.

- **Site:** `https://jadejaharsh30-tech.github.io/netra-data-universe/` has two views: *Data Universe* (`#universe`) and *Control Room* (`#control-room`).
- **304 metrics.** Each comes with its definition, free source, paid source, gotchas and Netra usage. They live in `agents/catalog_seed.json`, and the published version is in `data/catalog.json`.

## Agents
| Agent | Runs on | Schedule (IST) | Owns |
|---|---|---|---|
| Valuation | GitHub Actions | Weekdays 19:07, catch-up 07:53 | P/E, P/B, DY, EPS, ROE for 24 Nifty indices; India Co. EPS by year |
| Flows | GitHub Actions | Mon–Sat 09:11 | FPI monthly flows (NSDL), rolling sums, percentiles |
| External & Rupee | GitHub Actions | Weekdays 07:23 | USD/INR, BIS REER/NEER, India–US rates, real rates, EM FX |
| Netra Scout | Claude (needs PC + Chrome) | 5th–9th monthly 11:47 | New Netra editions → archive, catalog, cross-checks |
| Supervisor | Claude | Daily 19:59 + on call | Health checks, failure fixes, anomaly checks |

Planned agents (Ownership & Supply, India Macro, Rates & Credit, Global & US, Commodities, Market Regime) show their starter data as *snapshot* until they go live.

**On call**
- **GitHub agents:** Actions tab → pick the agent → *Run workflow*. Any push that changes `workers/<agent>.py` also re-runs that agent.
- **Claude agents:** ask Claude "run the Supervisor agent".

## Layout
```
agents/      registry.json (who does what), catalog_seed.json (the 304 metrics), PLAYBOOK.md (Claude agents' instructions)
workers/     one Python file per data agent, plus common.py, catalog.py (publisher), status.py (status CLI), netra_scan.py
store/       raw history the workers extend (NSE daily valuations, NSDL monthly, FRED series)
data/        published: catalog.json, headline.json, events.json, series/*.json, netra/*.json
status/      agents/<id>.json (current state), runs/<id>.json (history), summary.json (Control Room feed)
```

## Run an agent on your PC (Windows cmd)
```
pip install -r requirements.txt
python -m workers.valuation
python -m workers.catalog
```
Then open the site locally with `python -m http.server 8000` and go to http://localhost:8000.

Data: NSE, NSDL, FRED (BIS, OECD), World Bank, ECB. Derived figures are for research only and are not investment advice.
