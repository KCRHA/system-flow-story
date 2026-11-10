"""Pre-commit suppression audit of the published dashboard JSON.

Runs from the attacker's point of view: it only sees what's in public/data
(no true counts), and tries to recover suppressed values. Independent of
pipeline/suppression.py on purpose, so it can catch gaps in that module's
own logic rather than re-running it.

Usage:  python3 scripts/audit_suppression.py [public/data]
Exit code 1 if any hard finding (anything except INFO) is present.

Scope (matches pipeline/suppression.py): a hidden value only counts as
exposed if it can be calculated from the other cells in the SAME selection a
reader sees — one dimension's categories vs overall, or one category's
sankey rows/columns/bucket totals — using only published numbers. Combining
across selections (overlapping dimensions, or chaining one solved cell into
another relationship) is out of scope by policy and not checked.

Checks
  A  visible count in 1..10
  B  row carries a suppression marker but still publishes a value
  C  a hidden value in 1..10 that is the only hidden cell in one additive
     relationship (total minus visible parts). Relationship families
     (crosstab rows/cols, sankey in/out, each dimension's categories vs
     overall, subregions vs Overall) are only used if they're EXACT on
     every fully-visible group in that file, so non-partitions (gender,
     ...) can't produce false positives.
  D  a relationship whose k hidden cells are all "*" (so each is >= 1) and
     sum to exactly k, forcing each one to 1
  H  derived field published next to a suppressed count it was built from
     (length stats, pct_returned, capacity per-household ratios)
  INFO  relationships whose hidden cells sum to < 11 (bounded, not exact)

Not a finding: capacity pct_utilization/bed_pct_utilization are unit/bed
night inventory, intentionally unsuppressed (see build_capacity.py).
"""
import collections
import glob
import json
import math
import os
import sys

T = 11
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "public", "data")
INFLOW = ["already_active", "newly_homeless", "return_from_housed", "return_from_inactive"]
OUTFLOW = ["still_active", "aged_out", "permanently_housed", "inactive", "deceased"]
PERIODS = ("month", "quarter", "year", "exit_quarter")

findings = collections.defaultdict(list)


def isnum(v):
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def load(path):
    return json.load(open(path))


def pcol(row):
    return next(c for c in PERIODS if c in row)


# ---------------------------------------------------------------- C/D
def exact_families(vals, cons):
    tot, ok = collections.Counter(), collections.Counter()
    for fam, tk, pks in cons:
        if vals[tk] is None or any(vals[k] is None for k in pks):
            continue
        tot[fam] += 1
        ok[fam] += abs(vals[tk] - sum(vals[k] for k in pks)) < 1e-6
    return {f for f in tot if ok[f] == tot[f]}, {f: (ok[f], tot[f]) for f in tot}


def selection_attack(label, vals, cons, describe, markers):
    cons = [c for c in cons if c[1] in vals and all(k in vals for k in c[2])]
    exact, table = exact_families(vals, cons)
    skipped = sorted(f for f in table if f not in exact)
    cons = [c for c in cons if c[0] in exact]
    known = vals
    for fam, tk, pks in cons:
        unknown = [k for k in (tk, *pks) if known[k] is None]
        if len(unknown) != 1:
            continue
        u = unknown[0]
        v = sum(known[k] for k in pks) if u == tk else known[tk] - sum(known[k] for k in pks if k != u)
        if 0 < v < T:
            findings["C. small value recoverable within its selection"].append(f"{label}: {describe(u)} = {v:g} (via {fam})")
        if v < 0:
            findings["C. small value recoverable within its selection"].append(f"{label}: {describe(u)} solved NEGATIVE {v:g} (data inconsistent)")
    for fam, tk, pks in cons:
        unk = [k for k in (tk, *pks) if known[k] is None]
        if len(unk) < 2 or tk in unk:
            continue
        resid = known[tk] - sum(known[k] for k in pks if known[k] is not None)
        # Only "*" cells are known to be >= 1. "**" can be a hidden zero (a
        # zero is picked as a last resort), and insufficient_population or a
        # count hidden because its row was hidden can be 0 too, so the
        # all-1s inference only holds when every hidden cell is "*".
        if any(markers.get(k) != "*" for k in unk):
            continue
        if resid == len(unk):
            findings["D. hidden cells forced to all 1s"].append(f"{label}: {describe(tk)} [{fam}] {len(unk)} hidden sum to {resid:g}")
        elif 0 < resid < T:
            findings["INFO. hidden cells bounded under 11"].append(f"{label}: {describe(tk)} [{fam}] {len(unk)} hidden sum to {resid:g}")
    if skipped:
        findings["INFO. non-exact constraint families skipped"].append(f"{label}: {', '.join(skipped)}")


# ---------------------------------------------------------------- flow
def flow_key(r):
    return (r[pcol(r)], r["population_segment"], r["dimension"], r["category"], r["flow_type"])


def flow_constraints(vals):
    cons = []
    dimcats = collections.defaultdict(set)
    scopes, fts = set(), set()
    for (p, s, d, c, ft) in vals:
        dimcats[d].add(c)
        scopes.add((p, s))
        fts.add(ft)
    for (p, s) in scopes:
        for d, cs in dimcats.items():
            if d != "overall":
                for ft in fts:
                    cons.append((f"categories:{d}", (p, s, "overall", "Overall", ft), [(p, s, d, c, ft) for c in cs]))
            for c in cs:
                K = lambda ft: (p, s, d, c, ft)
                for i in INFLOW:
                    cons.append(("crosstab_row", K(f"indiv_{i}"), [K(f"indiv_flow_{i}_to_{o}") for o in OUTFLOW]))
                for o in OUTFLOW:
                    cons.append(("crosstab_col", K(f"indiv_{o}"), [K(f"indiv_flow_{i}_to_{o}") for i in INFLOW]))
                cons.append(("sankey_in", K("experienced_homelessness"), [K(f"indiv_{i}") for i in INFLOW]))
                cons.append(("sankey_out", K("experienced_homelessness"), [K(f"indiv_{o}") for o in OUTFLOW]))
    return cons


def audit_flow(label, paths):
    vals, rows = {}, {}
    for path in paths:
        for r in load(path):
            v = r["count"]
            if isnum(v) and 0 < v < T:
                findings["A. visible count 1..10"].append(f"{label}: {flow_key(r)} = {v:g}")
            if r["suppression_marker"] is not None and isnum(v):
                findings["B. marked but value published"].append(f"{label}: {flow_key(r)}")
            vals[flow_key(r)] = v if isnum(v) else None
            rows[flow_key(r)] = r
    cons = flow_constraints(vals)
    selection_attack(label, vals, cons, lambda k: "/".join(map(str, k)), {k: r["suppression_marker"] for k, r in rows.items()})


# ---------------------------------------------------------------- length
def audit_length(path):
    label = os.path.basename(path)
    rows = load(path)
    vals, markers = {}, {}
    for r in rows:
        n = r["n"]
        k = (r[pcol(r)], r["population_segment"], r.get("exit_type"), r["dimension"], r["category"])
        if isnum(n) and 0 < n < T:
            findings["A. visible count 1..10"].append(f"{label}: {k} n={n:g}")
        if r["suppression_marker"] is not None and isnum(n):
            findings["B. marked but value published"].append(f"{label}: {k}")
        if not isnum(n) and any(isnum(r.get(c)) for c in ("median_days", "p25_days", "p75_days", "mean_days")):
            findings["H. derived field published with its count hidden"].append(f"{label}: {k} stats shown, n hidden")
        vals[k] = n if isnum(n) else None
        markers[k] = r["suppression_marker"]
    cons = collections.defaultdict(list)
    for (p, s, e, d, c) in vals:
        if d != "overall":
            cons[(p, s, e, d)].append((p, s, e, d, c))
    selection_attack(label, vals, [(f"categories:{d}", (p, s, e, "overall", "Overall"), ks) for (p, s, e, d), ks in cons.items()],
                     lambda k: "/".join(map(str, k)), markers)


# ---------------------------------------------------------------- returns
def audit_returns(path):
    label = os.path.basename(path)
    rows = load(path)
    for col, mcol in (("n_exited", "suppression_marker"), ("n_returned", "return_suppression_marker")):
        vals, markers = {}, {}
        for r in rows:
            k = (r["exit_quarter"], r["population_segment"], r["dimension"], r["category"])
            v = r[col]
            if isnum(v) and 0 < v < T:
                findings["A. visible count 1..10"].append(f"{label}: {k} {col}={v:g}")
            vals[k] = v if isnum(v) else None
            markers[k] = r.get(mcol)
        cons = collections.defaultdict(list)
        for (p, s, d, c) in vals:
            if d != "overall":
                cons[(p, s, d)].append((p, s, d, c))
        selection_attack(f"{label}:{col}", vals, [(f"categories:{d}", (p, s, "overall", "Overall"), ks) for (p, s, d), ks in cons.items()],
                         lambda k: "/".join(map(str, k)), markers)
    for r in rows:
        k = (r["exit_quarter"], r["population_segment"], r["dimension"], r["category"])
        if r["suppression_marker"] is not None and isnum(r["n_exited"]):
            findings["B. marked but value published"].append(f"{label}: {k} n_exited")
        if r.get("return_suppression_marker") is not None and isnum(r["n_returned"]):
            findings["B. marked but value published"].append(f"{label}: {k} n_returned")
        if not isnum(r["n_returned"]) and isnum(r["pct_returned"]):
            findings["H. derived field published with its count hidden"].append(f"{label}: {k} pct_returned shown, n_returned hidden")


# ---------------------------------------------------------------- capacity
CAP_DERIVED = {"enrolled": ["throughput_hh_per_unit"], "active": ["households_per_unit"], "exited": ["pct_exited"]}


def audit_capacity(path):
    label = os.path.basename(path)
    rows = load(path)
    counts = [c for c in ("enrolled", "exited", "active") if c in rows[0]]
    for c in counts:
        vals, markers = {}, {}
        for r in rows:
            k = (r[pcol(r)], r["project_type"], r["subregion"])
            v = r[c]
            if isnum(v) and 0 < v < T:
                findings["A. visible count 1..10"].append(f"{label}: {k} {c}={v:g}")
            if r.get(f"{c}_suppression_marker") is not None and isnum(v):
                findings["B. marked but value published"].append(f"{label}: {k} {c}")
            if not isnum(v):
                for dcol in CAP_DERIVED[c]:
                    if isnum(r.get(dcol)):
                        findings["H. derived field published with its count hidden"].append(f"{label}: {k} {dcol} shown, {c} hidden")
            vals[k] = v if isnum(v) else None
            markers[k] = r.get(f"{c}_suppression_marker")
        cons = collections.defaultdict(list)
        for (p, pt, sr) in vals:
            if sr != "Overall":
                cons[(p, pt)].append((p, pt, sr))
        selection_attack(f"{label}:{c}", vals, [("subregions", (p, pt, "Overall"), ks) for (p, pt), ks in cons.items()],
                         lambda k: "/".join(map(str, k)), markers)


# ---------------------------------------------------------------- main
def main():
    audit_flow("flow_yearly", [f"{DATA}/dashboard_flow_yearly.json"])
    audit_flow("flow_quarterly", sorted(glob.glob(f"{DATA}/dashboard_flow_quarterly_*.json")))
    for p in sorted(glob.glob(f"{DATA}/dashboard_flow_monthly_*.json")):
        audit_flow(os.path.basename(p), [p])
    for p in sorted(glob.glob(f"{DATA}/dashboard_length*.json")):
        audit_length(p)
    audit_returns(f"{DATA}/dashboard_return_cohorts.json")
    for p in sorted(glob.glob(f"{DATA}/dashboard_capacity_*.json")):
        audit_capacity(p)

    hard = 0
    for cat in sorted(findings):
        items = findings[cat]
        is_info = cat.startswith("INFO")
        hard += 0 if is_info else len(items)
        print(f"\n== {cat}: {len(items)}")
        for m in items[: (3 if is_info else 10)]:
            print("    " + m)
    print(f"\n{'FAIL' if hard else 'PASS'}: {hard} hard finding(s)")
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
