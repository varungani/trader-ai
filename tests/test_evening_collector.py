"""
Tests for Evening Analytics & Decisions Archiver
Verifies local data collection, CSV tabular exports, JSON snapshots,
and instant pandas loaders for offline EDA.
"""
import os
import shutil
import pytest
import pandas as pd

from engine.analytics.evening_collector import (
    ensure_analytics_dirs,
    archive_evening_snapshot,
    load_trades_df,
    load_equity_df,
    load_decisions_df,
)


@pytest.fixture
def temp_analytics_dir(tmp_path):
    d = str(tmp_path / "analytics_test")
    yield d
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)


def test_ensure_analytics_dirs(temp_analytics_dir):
    paths = ensure_analytics_dirs(temp_analytics_dir)
    assert os.path.exists(paths["base"])
    assert os.path.exists(paths["snapshots"])
    assert paths["equity_csv"].endswith("track_daily_equity.csv")
    assert paths["ledger_jsonl"].endswith("decisions_ledger.jsonl")


def test_archive_evening_snapshot_creates_all_artifacts(temp_analytics_dir):
    res = archive_evening_snapshot(output_dir=temp_analytics_dir, perform_audit=False, custom_date="2026-11-23")
    assert res["status"] == "SUCCESS"
    assert os.path.exists(res["snapshot_path"])
    assert os.path.exists(res["paths"]["equity_csv"])
    assert os.path.exists(res["paths"]["positions_csv"])
    assert os.path.exists(res["paths"]["ledger_jsonl"])

    # 1. Verify daily equity table
    from engine.strategies.registry import default_registry
    num_tracks = len(default_registry.all())
    expected_track_ids = {s.track_id for s in default_registry.all()}

    df_eq = load_equity_df(temp_analytics_dir)
    assert not df_eq.empty
    assert len(df_eq) == num_tracks
    assert set(df_eq["track_id"]) == expected_track_ids
    assert "available_cash" in df_eq.columns
    assert "total_net_pnl_inr" in df_eq.columns

    # 2. Verify decisions ledger
    df_dec = load_decisions_df(temp_analytics_dir)
    # Even if empty or with initial events, must load cleanly
    assert isinstance(df_dec, pd.DataFrame)


def test_upsert_equity_does_not_duplicate_same_day(temp_analytics_dir):
    from engine.strategies.registry import default_registry
    num_tracks = len(default_registry.all())

    # Run once
    archive_evening_snapshot(output_dir=temp_analytics_dir, perform_audit=False, custom_date="2026-11-23")
    df1 = load_equity_df(temp_analytics_dir)
    assert len(df1) == num_tracks

    # Run again for the same date (e.g. re-running in evening)
    archive_evening_snapshot(output_dir=temp_analytics_dir, perform_audit=False, custom_date="2026-11-23")
    df2 = load_equity_df(temp_analytics_dir)
    # Must still have exactly num_tracks rows (updated, not duplicated!)
    assert len(df2) == num_tracks
