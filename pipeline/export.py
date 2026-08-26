"""Orchestrates the dashboard_* export: pull source tables from Synapse,
build the four tidy tables, apply suppression, validate, write JSON.

Run locally (after `az login`):
    python -m pipeline.export

In CI, AZURE_CLIENT_ID/SECRET/TENANT_ID env vars stand in for `az login`
(see connection.py and .github/workflows/sync-dashboard-data.yml).
"""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from . import connection
from .build_capacity import build_capacity_quarterly_rows, build_capacity_rows, build_capacity_yearly_rows
from .build_flow import build_flow_rows, build_resource_access_rows
from .build_length import build_length_rows
from .build_return_cohorts import build_return_cohort_rows
from .config import PROJECT_TYPE_CODE_TEXT_TO_HUD, RETURN_WINDOW_DAYS, get_export_window
from .suppression import TRUE_COUNT_COL, apply_full_suppression_pipeline, validate

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "public" / "data"


def _scope_to_window(df: pd.DataFrame, date_col: str, start: date, end: date) -> pd.DataFrame:
    return df[(df[date_col] >= pd.Timestamp(start)) & (df[date_col] <= pd.Timestamp(end))]


def _to_json_records(df: pd.DataFrame, date_cols: list[str]) -> list[dict]:
    df = df.drop(columns=[TRUE_COUNT_COL], errors="ignore").copy()
    for col in date_cols:
        df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d")
    # NaN/NaT -> null in the JSON output, not the string "NaN"
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _write(name: str, records: list[dict]):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(json.dumps(records, indent=2))
    print(f"wrote {len(records)} rows -> {path}")


def main():
    start, end = get_export_window()
    print(f"export window: {start} .. {end}")
    as_of = pd.Timestamp(date.today())

    conn = connection.get_connection()

    # Client_Demographics: per-person (PersonalID) RaceAndEthnicity/Gender/
    # VeteranStatus — joined into both episode_systemwide and
    # All_Program_Enrollments below, neither of which carries these natively.
    # Synapse table is singular ("client_demographic"), unlike its Looker
    # view name / the notebook it was ported from — confirmed against
    # INFORMATION_SCHEMA.TABLES directly, not assumed.
    client_demographics = connection.query(conn, "client_demographic")

    # Pull with no date trim for episode_systemwide: return-cohort detection
    # needs to see up to RETURN_WINDOW_DAYS past the window's end, and the
    # length/flow builders trim to the window themselves below.
    all_episodes = connection.query(conn, "episode_systemwide")
    all_episodes["TimePeriodStartDate"] = pd.to_datetime(all_episodes["TimePeriodStartDate"])
    all_episodes["EpisodeStartDate"] = pd.to_datetime(all_episodes["EpisodeStartDate"])
    all_episodes["EpisodeEndDate"] = pd.to_datetime(all_episodes["EpisodeEndDate"])
    # episode_systemwide fans out one row per (PersonalID, ClientUniqueIdentifier)
    # pair for anyone with multiple CUIs on file (see Episode_Systemwide notebook's
    # final CUI-merge step) — every column but ClientUniqueIdentifier, which we
    # never use, is identical across the fan-out, so this collapses it safely
    # without risking merging two genuinely different episode-months.
    all_episodes = all_episodes.drop_duplicates(subset=["PersonalID", "EpisodeID", "TimePeriodStartDate"])
    all_episodes = all_episodes.merge(
        client_demographics[["PersonalID", "RaceAndEthnicity", "Gender", "VeteranStatus"]],
        on="PersonalID",
        how="left",
    )

    episodes_in_window = _scope_to_window(all_episodes, "TimePeriodStartDate", start, end)

    episode_ce = connection.query(conn, "episode_ce")
    episode_ce["CEEntryDate"] = pd.to_datetime(episode_ce["CEEntryDate"])
    episode_ce["CEExitDate"] = pd.to_datetime(episode_ce["CEExitDate"])

    performance_metrics = connection.query(conn, "program_performance_metrics")
    performance_metrics["TimePeriodStartDate"] = pd.to_datetime(performance_metrics["TimePeriodStartDate"])
    performance_metrics["TimePeriodEndDate"] = pd.to_datetime(performance_metrics["TimePeriodEndDate"])
    performance_metrics = _scope_to_window(performance_metrics, "TimePeriodStartDate", start, end)

    program_attributes = connection.query(conn, "program_attributes")
    # Synapse stores the human-readable HUD label here, not the numeric code
    # CAPACITY_PROJECT_TYPE_GROUPS is keyed by — see config.py.
    program_attributes["ProjectTypeCode"] = program_attributes["ProjectTypeCode"].map(PROJECT_TYPE_CODE_TEXT_TO_HUD)

    # --- dashboard_flow_monthly ---
    flow_df = build_flow_rows(episodes_in_window, episode_ce)

    enrollments = connection.query(conn, "all_program_enrollments")
    enrollments["ProjectStartDate"] = pd.to_datetime(enrollments["ProjectStartDate"])
    enrollments["ProjectExitDate"] = pd.to_datetime(enrollments["ProjectExitDate"])
    # Same text-label-vs-numeric-code mismatch as program_attributes above.
    enrollments["ProjectTypeCode"] = enrollments["ProjectTypeCode"].map(PROJECT_TYPE_CODE_TEXT_TO_HUD)
    # All_Program_Enrollments has no monthly grain of its own (each row spans
    # ProjectStartDate..ProjectExitDate) — build_resource_access_rows expands
    # it against the same month list every other table uses.
    months_in_window = sorted(episodes_in_window["TimePeriodStartDate"].unique())
    resource_df = build_resource_access_rows(enrollments, client_demographics, months_in_window)
    flow_df = pd.concat([flow_df, resource_df], ignore_index=True)

    flow_df = apply_full_suppression_pipeline(flow_df, group_cols=["month", "population_segment", "dimension", "flow_type"])
    flow_violations = validate(flow_df, group_cols=["month", "population_segment", "dimension", "flow_type"])

    # --- dashboard_length_monthly ---
    length_df = build_length_rows(episodes_in_window)
    length_df = apply_full_suppression_pipeline(length_df, group_cols=["month", "population_segment", "dimension"], count_col="count")
    length_violations = validate(length_df, group_cols=["month", "population_segment", "dimension"], count_col="count")
    # The suppression pipeline only nulls the count column itself — the
    # derived distribution stats are just as revealing for a small n, so they
    # must be nulled alongside it, not left populated next to a "*"/"**".
    length_df.loc[length_df["suppression_marker"].notna(), ["median_days", "p25_days", "p75_days", "mean_days"]] = None
    length_df = length_df.rename(columns={"count": "n"})

    # --- dashboard_return_cohorts ---
    return_df = build_return_cohort_rows(episodes_in_window, all_episodes, as_of=as_of)
    return_df = return_df.rename(columns={"n_exited": "count"})
    return_df = apply_full_suppression_pipeline(return_df, group_cols=["exit_quarter", "population_segment", "dimension"], count_col="count")
    return_violations = validate(return_df, group_cols=["exit_quarter", "population_segment", "dimension"], count_col="count")
    return_df = return_df.rename(columns={"count": "n_exited"})
    return_df.loc[return_df["suppression_marker"].notna(), "n_returned"] = None
    return_df.loc[return_df["suppression_marker"].notna(), "pct_returned"] = None

    # --- dashboard_capacity_monthly / _quarterly / _yearly (no
    # suppression: aggregate inventory data, not person-level) ---
    capacity_df = build_capacity_rows(performance_metrics, program_attributes, as_of=as_of)
    capacity_quarterly_df = build_capacity_quarterly_rows(performance_metrics, program_attributes, as_of=as_of)
    # Yearly deliberately doesn't get this treatment — the current
    # (incomplete) year is intentionally included there, labeled
    # "year to date" by the frontend's existing Year selector, unlike
    # the quarterly/monthly charts which should only ever show complete
    # periods.
    capacity_yearly_df = build_capacity_yearly_rows(performance_metrics, program_attributes)

    all_violations = flow_violations + length_violations + return_violations
    if all_violations:
        print("SUPPRESSION VALIDATION FAILED:", file=sys.stderr)
        for v in all_violations:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)

    _write("dashboard_flow_monthly.json", _to_json_records(flow_df, ["month"]))
    _write("dashboard_length_monthly.json", _to_json_records(length_df, ["month"]))
    _write("dashboard_return_cohorts.json", _to_json_records(return_df, ["exit_quarter"]))
    _write("dashboard_capacity_monthly.json", _to_json_records(capacity_df, ["month"]))
    _write("dashboard_capacity_quarterly.json", _to_json_records(capacity_quarterly_df, ["quarter"]))
    _write("dashboard_capacity_yearly.json", _to_json_records(capacity_yearly_df, []))


if __name__ == "__main__":
    main()
