"""Unit tests for the pure decision logic: risk, alarms, entry."""

from __future__ import annotations

from datetime import time
from decimal import Decimal

from tiger import alarms, entry, risk
from tiger.alarms import AlarmAction
from tiger.state import Direction


# ----------------------------- risk ----------------------------- #
def test_position_size_floors():
    assert risk.position_size(Decimal("100")) == 250          # 25000/100
    assert risk.position_size(Decimal("103.33")) == 241       # floor


def test_hard_stop_is_500_loss():
    shares = risk.position_size(Decimal("100"))               # 250
    stop = risk.hard_stop_price(Direction.LONG, Decimal("100"), shares)
    assert (Decimal("100") - stop) * shares == Decimal("500")
    stop_s = risk.hard_stop_price(Direction.SHORT, Decimal("100"), shares)
    assert (stop_s - Decimal("100")) * shares == Decimal("500")


def test_ratchet_only_tightens():
    # long: existing stop 95, price 100 -> proposed 99.75 -> tighter, takes it
    assert risk.ratchet_stop(Direction.LONG, Decimal("100"), Decimal("95")) == Decimal("99.75")
    # long: existing stop 99.9 already tighter than 99.75 -> keep 99.9
    assert risk.ratchet_stop(Direction.LONG, Decimal("100"), Decimal("99.9")) == Decimal("99.9")
    # short: existing 105, price 100 -> proposed 100.25 -> tighter, takes it
    assert risk.ratchet_stop(Direction.SHORT, Decimal("100"), Decimal("105")) == Decimal("100.25")


def test_circuit_breaker():
    assert not risk.circuit_breaker_tripped(Decimal("-1499"))
    assert risk.circuit_breaker_tripped(Decimal("-1500"))


# ----------------------------- alarms ----------------------------- #
def test_divergence_long_and_short():
    # long: higher price, lower rsi -> divergence
    assert alarms.divergence(Direction.LONG, 101, 60, 100, 70) is True
    assert alarms.divergence(Direction.LONG, 101, 80, 100, 70) is False
    # short: lower price, higher rsi -> divergence
    assert alarms.divergence(Direction.SHORT, 99, 40, 100, 30) is True
    # no stored peak yet -> no divergence
    assert alarms.divergence(Direction.LONG, 101, 60, None, None) is False


def test_alarm_a_flash_move():
    # long, >1% drop close-to-close
    assert alarms.alarm_a_flash_move(Direction.LONG, 100, 98.5).action is AlarmAction.EXIT
    assert alarms.alarm_a_flash_move(Direction.LONG, 100, 99.5).action is AlarmAction.NONE
    # short, >1% rise is adverse
    assert alarms.alarm_a_flash_move(Direction.SHORT, 100, 101.5).action is AlarmAction.EXIT


def test_alarm_b_trend_death():
    assert alarms.alarm_b_trend_death(Direction.LONG, 99, 100).action is AlarmAction.EXIT
    assert alarms.alarm_b_trend_death(Direction.LONG, 101, 100).action is AlarmAction.NONE
    assert alarms.alarm_b_trend_death(Direction.SHORT, 101, 100).action is AlarmAction.EXIT


def test_alarm_c_three_declines():
    assert alarms.alarm_c_tiger_grip([40, 30, 20, 10]).action is AlarmAction.RATCHET
    assert alarms.alarm_c_tiger_grip([10, 30, 20, 10]).action is AlarmAction.NONE
    assert alarms.alarm_c_tiger_grip([20, 10]).action is AlarmAction.NONE  # too few


def test_alarm_d_hvp_lock():
    # peak 40, current 29 < 30 (75%) -> exit
    assert alarms.alarm_d_hvp_lock(29, 40).action is AlarmAction.EXIT
    assert alarms.alarm_d_hvp_lock(31, 40).action is AlarmAction.NONE


# ----------------------------- entry ----------------------------- #
def test_two_consecutive_beyond():
    assert entry.two_consecutive_beyond([99, 101, 102], 100, Direction.LONG) is True
    assert entry.two_consecutive_beyond([99, 101, 99.5], 100, Direction.LONG) is False
    assert entry.two_consecutive_beyond([101, 99, 98], 100, Direction.SHORT) is True


def test_weather_ok():
    assert entry.weather_ok(Direction.LONG, 101, 100, 101, 100) is True
    assert entry.weather_ok(Direction.LONG, 99, 100, 101, 100) is False


def test_volume_gate_skipped_before_10():
    assert entry.volume_ok(1, 999, time(9, 45)) is True       # skipped pre-10:00
    assert entry.volume_ok(100, 100, time(10, 30)) is True    # >= passes
    assert entry.volume_ok(99, 100, time(10, 30)) is False    # below fails
    assert entry.volume_ok(100, None, time(10, 30)) is False  # unknown avg fails


def test_sizing_thresholds():
    assert entry.sizing_ok(Direction.LONG, 35, None) == (True, True)   # >30 full
    assert entry.sizing_ok(Direction.LONG, 27, None) == (True, False)  # 25-30 scaled
    assert entry.sizing_ok(Direction.LONG, 20, None) == (False, False)  # <25 no entry
