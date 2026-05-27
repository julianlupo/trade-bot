"""Tests for the indicator validation report (offline, synthetic data)."""

from __future__ import annotations

import pandas as pd

from tiger import data, validate


def test_compute_validation_columns_and_warm_values():
    stock, _ = data.synthetic_session(seed=0)
    df1, df5 = validate.compute_validation(stock)

    assert {"RSI(15)", "ADX(14)", "DI+(14)", "DI-(14)"} <= set(df1.columns)
    assert {"ADX(14)", "DI+(14)", "DI-(14)", "EMA(9)", "VWAP"} <= set(df5.columns)

    # by the target morning, warmed-up values should be present (not NaN)
    target = pd.DatetimeIndex(df1.index.normalize().unique())[-1]
    mid = df1[df1.index.normalize() == target].between_time("10:00", "10:05")
    assert mid["RSI(15)"].notna().all()
    assert mid["ADX(14)"].notna().all()


def test_build_report_has_sections():
    stock, _ = data.synthetic_session(seed=0)
    df1, df5 = validate.compute_validation(stock)
    report = validate.build_report("SYNTH", df1, df5)
    assert "Indicator Validation" in report
    assert "1-minute indicators" in report
    assert "5-minute indicators" in report
    assert "RSI" in report and "VWAP" in report
