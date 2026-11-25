"""Netra Scout helper: scan one Netra PDF, tag which catalog metrics it uses, list unmatched chart titles as
candidate new metrics, and update agents/catalog_seed.json + agents/netra_editions.json.
  python -m workers.netra_scan <path-to-pdf> <YYYY-MM>"""
import json, re, subprocess, sys
from .common import ROOT, DATA, rj, wj, now


def charty(l):
    w = l.split()
    return 2 <= len(w) <= 18 and sum(c.isdigit() for c in l) <= len(l) * 0.2 and sum(1 for x in w if x[:1].isupper()) >= 0.5 * len(w)


def pages(pdf):
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout).group(1))
    for p in range(1, n + 1):
        t = subprocess.run(["pdftotext", "-layout", "-f", str(p), "-l", str(p), pdf, "-"], capture_output=True, text=True).stdout
        yield p, [l.strip() for l in t.split("\n") if l.strip()]


def main(pdf, ed):
    seed_p, eds_p = ROOT / "agents" / "catalog_seed.json", ROOT / "agents" / "netra_editions.json"
    seed, eds = rj(seed_p), rj(eds_p)
    pg = list(pages(pdf))
    heads = [(p, " | ".join([L[0]] + [l for l in L[1:] if charty(l)]) if L else "") for p, L in pg]
    full = " ".join(" ".join(L) for _, L in pg)
    matched, used_pages = [], set()
    for e in seed:
        if "xx_not_in_netra" in e["rx"]:
            continue
        rx = re.compile(e["rx"])
        hit = [p for p, h in heads if rx.search(h)]
        if hit or rx.search(full):
            matched.append({"metric": e["metric"], "pages": hit, "where": "chart title" if hit else "body text"})
            used_pages.update(hit)
            if ed not in eds["editions"]:
                e["n"] = e.get("n", 0) + 1
                first = re.search(r"\((\d{4}-\d\d)", e.get("netra", ""))
                e["netra"] = f"{e['n']} editions ({first.group(1) if first else ed} → {ed})"
    cands = [{"page": p, "title": h[:220]} for p, h in heads if p not in used_pages and h and len(h.split()) >= 3][:80]
    wj(DATA / "netra" / f"{ed}.json", {"edition": ed, "scanned": now(), "pages": len(pg), "matched": matched, "candidates": cands}, 1)
    if ed not in eds["editions"]:
        eds["editions"] = sorted(eds["editions"] + [ed])
        wj(eds_p, eds, 1); wj(seed_p, seed)
    print(f"{ed}: {len(pg)} pages, {len(matched)} catalog metrics used, {len(cands)} candidate pages for new metrics")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
