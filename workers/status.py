"""Status CLI for Claude agents and manual use.
  python -m workers.status start  <agent> "<what it is doing>"
  python -m workers.status task   <agent> "<what it is doing now>"
  python -m workers.status finish <agent> ok|failed "<message>" [rows] [data_through]
  python -m workers.status event  <agent> <kind> "<text>"
Then run: python -m workers.catalog   (refreshes the Control Room feed)"""
import sys
from .common import set_status, add_run, add_events, now, next_run, trigger_kind, run_url, rj, status_path


def main(a):
    cmd, agent = a[0], a[1]
    if cmd == "start":
        set_status(agent, state="running", task=a[2] if len(a) > 2 else "Running", started=now(), error=None)
    elif cmd == "task":
        set_status(agent, task=a[2])
    elif cmd == "finish":
        outcome, msg = a[2], a[3] if len(a) > 3 else ""
        rows = int(a[4]) if len(a) > 4 else 0
        st = rj(status_path(agent), {})
        kw = dict(state="ok" if outcome == "ok" else "failed", finished=now(), message=msg, rows_updated=rows,
                  task="Idle — waiting for next schedule" if outcome == "ok" else "Failed — needs attention", next_run=next_run(agent))
        if outcome == "ok":
            kw.update(last_success=now(), error=None)
        else:
            kw.update(error=msg)
        if len(a) > 5:
            kw["data_through"] = a[5]
        set_status(agent, **kw)
        add_run(agent, {"started": st.get("started"), "finished": now(), "outcome": outcome, "rows": rows, "message": msg,
                        "trigger": trigger_kind(), "url": run_url()})
    elif cmd == "event":
        add_events(agent, [{"kind": a[2], "text": a[3]}])
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) if len(sys.argv) > 2 else (print(__doc__) or 2))
