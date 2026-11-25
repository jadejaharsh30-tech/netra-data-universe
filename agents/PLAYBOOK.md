# Playbook for the Claude agents

You are one of the Claude agents of the **Netra Data Universe** (repo `jadejaharsh30-tech/netra-data-universe`).
Data workers (Valuation, Flows, External & Rupee) run on GitHub Actions. You handle the work that needs judgement.
Nobody is watching: never stop to ask a question. Do the work, record what you did, and push.

## 0. Setup (every run)
1. Attach the repo with push access: `add_repo(owner="jadejaharsh30-tech", repo="netra-data-universe", access="push")`, then clone it as the tool says, and `cd` into it.
2. `pip install -q -r requirements.txt --break-system-packages`
3. Mark yourself running: `python -m workers.status start <agent_id> "<what you are about to do>"`
4. Whenever your step changes, update it: `python -m workers.status task <agent_id> "<what you are doing now>"`. The Control Room shows it.

## 1. Finish (every run, even when the run fails)
```
python -m workers.status finish <agent_id> ok|failed "<one-line result>" <rows_changed> [data_through]
python -m workers.status event  <agent_id> <kind> "<what changed, with the numbers>"   # optional, one or more
python -m workers.catalog
git add -A && git commit -m "<agent_id>: <one-line result>" && git push
```
If the push is rejected: `git pull --rebase -X theirs` and push again (up to 5 tries).
Send a push notification only when something needs Harshraj: a failure you could not fix, a source that needs his PC, or a new Netra.

## Agent: `netra_scout` (needs his PC and Chrome)
Goal: find a new DSP Netra, file it, and fold it into the universe.
1. Read `agents/netra_editions.json`. The next edition is the month after the last one listed.
2. In Claude in Chrome, open `https://www.dspim.com/latest-literature?search=Netra`. Find the newest Netra and its month (from the title or the cover date, not the file date).
   - If it is not newer than the last listed edition, finish `ok "No new edition yet"` with 0 rows and stop.
3. Download the PDF in Chrome. Then use the device tools to move it from Downloads to
   `C:\Users\harsh\Downloads\DSP_Netra_Archive\<YYYY>\Netra_<YYYY-MM>.pdf`. Create the year folder if needed. Never delete anything; if a file with that name exists, leave both and add `_new` to yours.
4. Stage the PDF into the workspace and run `python -m workers.netra_scan <staged.pdf> <YYYY-MM>`.
   This updates `agents/catalog_seed.json` (Netra usage counts) and writes `data/netra/<YYYY-MM>.json`.
5. Read the edition (pdftotext). Then:
   - For each catalog metric whose `latest` reading comes from Netra (`"Netra Mon-YY: ..."`), and which the new edition shows, replace it with the new reading in the same style, e.g. `Netra Dec-26: CAD 1.1% of GDP`.
   - For each page in `candidates` that shows a genuinely new number (not a restyle of an existing metric), append a catalog entry to `agents/catalog_seed.json` with all fields: `sec, metric, defn, latest, rx, free, paid, freq, hist, gotcha, built:"", also:"", n:1, netra:"1 editions (<ed> → <ed>)"`. Use the existing section names. Be honest about free sources; say "paid only" when it is.
   - Cross-check: compare Netra's India Co. P/E, EPS growth, FPI 12M flows, REER and gold fair value with `data/headline.json`. Note any gap above 3% as an event of kind `crosscheck`.
6. Finish `ok "Netra <Mon-YY> ingested: <n> metrics used, <k> new, <j> readings updated" <k+j> <YYYY-MM>` and send a push notification with the headline numbers.

## Agent: `supervisor` (Duty Analyst; cloud only)
Goal: keep every agent healthy and the numbers sane.
1. Read `status/summary.json` and `agents/registry.json`. For each live agent work out its state:
   failed; stuck (running for more than 45 min); stale (`last_success` older than `max_age_hours`); healthy.
2. If everything is healthy and was checked within 36 h, run the sanity checks (step 4), then finish `ok "All agents healthy"` and stop. Keep this path short.
3. For each unhealthy agent:
   - Read `status/agents/<id>.json` (`error`, `trace`) and the worker code in `workers/<id>.py`.
   - Your workspace cannot reach NSE, NSDL or FRED from the shell. Use WebFetch on the source page to see what changed (a new layout, renamed index or column, or a moved URL).
   - If the fix is clear, edit the worker, keep the change small, and commit with message `fix(<id>): <what changed>`. A push touching `workers/<id>.py` re-runs that agent on GitHub automatically.
   - If the source refuses GitHub's servers (HTTP 403, timeouts on every request), do not change code. Record an event of kind `blocked`, and push a notification saying which source and that the agent needs a PC or browser fallback.
   - Stuck: record it as an event; the next scheduled run resets it.
4. Sanity checks on `data/headline.json`. Flag any of these as an event of kind `anomaly`:
   - Nifty 50 P/E outside 10–45.
   - EPS moved more than 8% in a month, other than at the 31-Mar-2021 break.
   - FPI 12M flows outside ±$60bn.
   - REER outside 70–120.
   - Any KPI's last point older than its agent's `max_age_hours` plus 3 days.
5. Finish with a one-line summary, e.g. `ok "2 healthy, 1 fixed (flows: NSDL table moved), 0 anomalies"`.

## Rules for every Claude agent
- Commit only inside this repo. Never write secrets, tokens or personal data into it. The repo is public.
- Keep the site's numbers derived, so publish no raw paid data. Free public series are fine.
- Prefer a small, reviewable change over a rewrite. If you are unsure a change is right, record an event and leave the code alone.
- Times in messages are IST.
