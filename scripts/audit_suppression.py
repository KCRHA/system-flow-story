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
     every fully-visible group in that file, or if their parts never exceed
     the total (a dimension whose "Unknown" isn't published): those get one
     extra hidden remainder cell that is 0 or more; that remainder itself
     is never reported.
  D  a relationship whose k hidden cells are all "*" (so each is >= 1) and
     sum to exactly k, forcing each one to 1
  H  derived field published next to a suppressed count it was built from
     (pct_returned, capacity per-household ratios)
  N  deceased_in_inactive (how many of an inactive count are deceased,
     published only as a band of 10): a nonzero count published as a
     number, a band that isn't 1-10/11-20/..., a band next to an inactive
     cell hidden by anything but "*", or a deceased count of 1..10 pinned
     by one dimension's categories vs overall
  O  a length-of-time table publishing n (it never should: medians are
     published for every group with anyone in it, so n is what identifies)
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
OUTFLOW = ["still_active", "aged_out", "permanently_housed", "inactive"]  # deceased is folded into inactive
DECEASED = "deceased_in_inactive"
REMAINDER = "<unpublished remainder>"  # key prefix for a subset family's implied hidden cell
DECEASED_BAND_WIDTH = 10
INF = float("inf")
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
    """Families exact on every fully-visible instance, and families whose
    parts never exceed the total (a dimension whose "Unknown" category isn't
    published): a reader treats the latter as exact plus one hidden
    remainder that is 0 or more."""
    tot, ok, le = collections.Counter(), collections.Counter(), collections.Counter()
    for fam, tk, pks in cons:
        if vals[tk] is None or any(vals[k] is None for k in pks):
            continue
        tot[fam] += 1
        diff = vals[tk] - sum(vals[k] for k in pks)
        ok[fam] += abs(diff) < 1e-6
        le[fam] += diff > -1e-6
    exact = {f for f in tot if ok[f] == tot[f]}
    subset = {f for f in tot if le[f] == tot[f]} - exact
    return exact, subset, {f: (ok[f], tot[f]) for f in tot}


def is_remainder(k):
    return isinstance(k, tuple) and len(k) and k[0] == REMAINDER


def selection_attack(label, vals, cons, describe, markers):
    cons = [c for c in cons if c[1] in vals and all(k in vals for k in c[2])]
    exact, subset, table = exact_families(vals, cons)
    skipped = sorted(f for f in table if f not in exact and f not in subset)
    # A subset family gets its unpublished remainder as one more hidden part.
    cons = [c if c[0] in exact else (c[0], c[1], [*c[2], (REMAINDER, c[0], c[1])]) for c in cons if c[0] in exact or c[0] in subset]
    known = collections.defaultdict(lambda: None, vals)
    for fam, tk, pks in cons:
        unknown = [k for k in (tk, *pks) if known[k] is None]
        if len(unknown) != 1:
            continue
        u = unknown[0]
        if is_remainder(u):
            continue  # an unpublished "Unknown" may be derivable; it identifies nobody
        v = sum(known[k] for k in pks) if u == tk else known[tk] - sum(known[k] for k in pks if k != u)
        if 0 < v < T:
            findings["C. small value recoverable within its selection"].append(f"{label}: {describe(u)} = {v:g} (via {fam})")
        if v < 0:
            findings["C. small value recoverable within its selection"].append(f"{label}: {describe(u)} solved NEGATIVE {v:g} (data inconsistent)")
    for fam, tk, pks in cons:
        # A remainder is 0 or more, so it can't stop k "*" cells summing to k
        # from all being 1 (it's then 0); it's left out of the count.
        unk = [k for k in (tk, *pks) if known[k] is None and not is_remainder(k)]
        if not unk or (len(unk) < 2 and not any(is_remainder(k) for k in pks)) or tk in unk:
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
    vals, rows, deceased_rows = {}, {}, []
    for path in paths:
        for r in load(path):
            if r["flow_type"] == DECEASED:
                deceased_rows.append(r)
                continue
            v = r["count"]
            if isnum(v) and 0 < v < T:
                findings["A. visible count 1..10"].append(f"{label}: {flow_key(r)} = {v:g}")
            if r["suppression_marker"] is not None and isnum(v):
                findings["B. marked but value published"].append(f"{label}: {flow_key(r)}")
            vals[flow_key(r)] = v if isnum(v) else None
            rows[flow_key(r)] = r
    cons = flow_constraints(vals)
    markers = {k: r["suppression_marker"] for k, r in rows.items()}
    selection_attack(label, vals, cons, lambda k: "/".join(map(str, k)), markers)
    audit_deceased(label, deceased_rows, vals, markers, cons)


def audit_deceased(label, rows, vals, markers, cons):
    """N: the deceased_in_inactive bands (see the module docstring)."""
    d_bounds = {}
    for r in rows:
        k = flow_key(r)[:4]
        inactive = (*k, "indiv_inactive")
        m, v = r["suppression_marker"], r["count"]
        if m is None:
            if not isnum(v) or v != 0:
                findings["N. deceased band problem"].append(f"{label}: {'/'.join(map(str, k))} deceased published as {v}")
            d_bounds[k] = (0, 0)
            continue
        if isnum(v):
            findings["B. marked but value published"].append(f"{label}: {'/'.join(map(str, k))} deceased")
        if m == "range":
            lo, hi = r.get("count_low"), r.get("count_high")
            if not (isnum(lo) and isnum(hi)) or hi - lo != DECEASED_BAND_WIDTH - 1 or (lo - 1) % DECEASED_BAND_WIDTH:
                findings["N. deceased band problem"].append(f"{label}: {'/'.join(map(str, k))} band [{lo}, {hi}] isn't a band of {DECEASED_BAND_WIDTH}")
                continue
            if markers.get(inactive) not in (None, "*"):
                findings["N. deceased band problem"].append(f"{label}: {'/'.join(map(str, k))} band next to inactive marked {markers.get(inactive)!r}")
            b = (lo, hi)
        elif m == "withheld":
            b = (1, INF)
        else:
            b = (0, INF)
        # A deceased count can't exceed its inactive cell: the number when
        # visible, 10 when "*".
        if inactive in vals:
            cap = vals[inactive] if vals[inactive] is not None else (T - 1 if markers.get(inactive) == "*" else INF)
            b = (b[0], min(b[1], cap))
        d_bounds[k] = b
    # Categories vs overall, only for dimensions whose indiv_inactive
    # categories add up exactly to overall in the published data.
    exact, subset, _ = exact_families(vals, [c for c in cons if c[1] in vals and all(k in vals for k in c[2]) and c[1][4] == "indiv_inactive"])
    groups = collections.defaultdict(list)
    for k in d_bounds:
        if k[2] != "overall":
            groups[(k[0], k[1], k[2])].append(k)
    for (p, s, d), ks in groups.items():
        fam = f"categories:{d}"
        tk = (p, s, "overall", "Overall")
        if tk not in d_bounds or (fam not in exact and fam not in subset):
            continue
        rk = (REMAINDER, fam, tk)
        members = [(tk, -1)] + [(k, 1) for k in ks] + ([(rk, 1)] if fam in subset else [])
        b = {**{k: d_bounds[k] for k in [tk, *ks]}, rk: (0, INF)}
        for k, c in members:
            if is_remainder(k) or b[k][1] == 0:
                continue
            o_lo = sum(b[k2][0] if c2 > 0 else -b[k2][1] for k2, c2 in members if k2 != k)
            o_hi = sum(b[k2][1] if c2 > 0 else -b[k2][0] for k2, c2 in members if k2 != k)
            x_lo, x_hi = (-o_hi, -o_lo) if c > 0 else (o_lo, o_hi)
            lo, hi = max(x_lo, b[k][0]), min(x_hi, b[k][1])
            if hi - lo < 0.5 and 0 < lo < T:
                findings["N. deceased band problem"].append(f"{label}: {'/'.join(map(str, k))} deceased pinned to {lo:g} (via {fam})")


# ---------------------------------------------------------------- length
def audit_length(path):
    """O: length tables publish medians for every group with anyone in it,
    so they must never publish the group's size."""
    label = os.path.basename(path)
    for r in load(path):
        if "n" in r:
            k = (r[pcol(r)], r["population_segment"], r.get("exit_type"), r["dimension"], r["category"])
            findings["O. length table publishes n"].append(f"{label}: {k} n={r['n']}")


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
