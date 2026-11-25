"""Shared plumbing for every agent: paths, HTTP, status records, run history, events, series files."""
import json, math, os, sys, time, traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE, DATA, STATUS = ROOT / "store", ROOT / "data", ROOT / "status"
IST = timezone(timedelta(hours=5, minutes=30))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rj(p, default=None):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def wj(p, obj, indent=None):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=indent, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def registry():
    return {a["id"]: a for a in rj(ROOT / "agents" / "registry.json")["agents"]}


def session():
    import requests
    from requests.adapters import HTTPAdapter, Retry
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])))
    return s


def next_run(agent):
    cron = registry()[agent].get("cron")
    if not cron:
        return None
    try:
        from croniter import croniter
        base = datetime.now(timezone.utc)
        return min(croniter(c, base).get_next(datetime) for c in cron).replace(microsecond=0).isoformat()
    except Exception:
        return None


def status_path(agent):
    return STATUS / "agents" / f"{agent}.json"


def set_status(agent, **kw):
    st = rj(status_path(agent), {"id": agent})
    st.update(kw)
    st["updated"] = now()
    wj(status_path(agent), st, 1)
    return st


def trigger_kind():
    ev = os.environ.get("GITHUB_EVENT_NAME", "")
    return {"schedule": "schedule", "workflow_dispatch": "manual", "push": "code change"}.get(ev, os.environ.get("AGENT_TRIGGER", "local"))


def run_url():
    s, r, i = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{s}/{r}/actions/runs/{i}" if s and r and i else None


def add_run(agent, rec, keep=60):
    p = STATUS / "runs" / f"{agent}.json"
    runs = rj(p, [])
    runs.insert(0, rec)
    wj(p, runs[:keep], 1)


def add_events(agent, events, keep=200):
    if not events:
        return
    p = DATA / "events" / f"{agent}.json"
    ev = rj(p, [])
    for e in events:
        ev.insert(0, {"t": now(), "agent": agent, **e})
    wj(p, ev[:keep], 1)


def clean(v, nd=4):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if math.isnan(f) or math.isinf(f):
        return None
    return float(f"{f:.{nd}g}") if abs(f) < 1e15 else f


def write_series(sid, df, agent, title, freq, note=""):
    """df: pandas DataFrame, first column = period key. Written as compact column/row JSON."""
    cols = list(df.columns)
    rows = [[r[0] if isinstance(r[0], str) else str(r[0])] + [clean(x) if not isinstance(x, str) else x for x in r[1:]]
            for r in df.itertuples(index=False, name=None)]
    wj(DATA / "series" / f"{sid}.json", {"id": sid, "title": title, "agent": agent, "freq": freq, "note": note,
                                           "updated": now(), "columns": cols, "rows": rows})
    return len(rows)


def run_agent(agent, fn):
    """Wrap a worker: mark running, run, record outcome + history, never lose the status on a crash."""
    t0 = time.time(); started = now()
    set_status(agent, state="running", task=registry()[agent].get("task_default", "Running"), started=started)
    rec = {"started": started, "trigger": trigger_kind(), "url": run_url()}
    try:
        res = fn() or {}
        dur = round(time.time() - t0, 1)
        st = set_status(agent, state="ok", task=res.get("idle_task", "Idle — waiting for next schedule"),
                        finished=now(), last_success=now(), duration_s=dur, rows_updated=res.get("rows", 0),
                        message=res.get("message", ""), data_through=res.get("data_through"), error=None,
                        warnings=res.get("warnings", []), next_run=next_run(agent))
        rec.update(outcome="ok", finished=st["finished"], duration_s=dur, rows=res.get("rows", 0), message=res.get("message", ""))
        add_run(agent, rec); add_events(agent, res.get("events"))
        print(f"[{agent}] ok in {dur}s: {res.get('message', '')}")
        return 0
    except Exception as e:
        dur = round(time.time() - t0, 1)
        err = f"{type(e).__name__}: {e}"[:600]
        st = set_status(agent, state="failed", task="Failed — waiting for Duty Analyst or a manual re-run", finished=now(),
                        duration_s=dur, error=err, trace=traceback.format_exc()[-2000:], next_run=next_run(agent))
        rec.update(outcome="failed", finished=st["finished"], duration_s=dur, rows=0, message=err)
        add_run(agent, rec)
        add_events(agent, [{"kind": "failure", "text": err}])
        print(f"[{agent}] FAILED: {err}", file=sys.stderr)
        return 1
