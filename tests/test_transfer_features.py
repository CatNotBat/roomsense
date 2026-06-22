"""Tests for TX-invariant transfer features."""
import sys, os
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from transfer_features import self_normalize, anisotropy, argmax_coverage, reference_node_delta


def test_self_normalize_basic():
    meds = {"s1": -50, "s2": -60, "s3": -70}
    result = self_normalize(meds, ["s1", "s2", "s3"])
    # ref = median([-50, -60, -70]) = -60
    assert result["s1"] == pytest.approx(10.0)
    assert result["s2"] == pytest.approx(0.0)
    assert result["s3"] == pytest.approx(-10.0)


def test_self_normalize_with_nan():
    meds = {"s1": -50, "s2": np.nan, "s3": -70}
    result = self_normalize(meds, ["s1", "s2", "s3"])
    # ref = median([-50, -70]) = -60
    assert result["s1"] == pytest.approx(10.0)
    assert np.isnan(result["s2"])
    assert result["s3"] == pytest.approx(-10.0)


def test_self_normalize_all_nan():
    meds = {"s1": np.nan, "s2": np.nan}
    result = self_normalize(meds, ["s1", "s2"])
    assert np.isnan(result["s1"])
    assert np.isnan(result["s2"])


def test_anisotropy_all_equal():
    assert anisotropy({"s1": -50, "s2": -50, "s3": -50}) == 0.0


def test_anisotropy_spread():
    # [-80, -70, -60, -50]: Q25=-72.5, Q75=-57.5, IQR=15 (numpy linear interp)
    result = anisotropy({"s1": -50, "s2": -60, "s3": -70, "s4": -80})
    assert result == pytest.approx(15.0)


def test_anisotropy_one_sensor():
    assert anisotropy({"s1": -50}) == 0.0


def test_argmax_coverage_single_sensor():
    # Same sensor always loudest → 1/3
    assert argmax_coverage(["s1", "s1", "s1"], 3) == pytest.approx(1 / 3)


def test_argmax_coverage_all_sensors():
    # Each sensor loudest once → 1.0
    assert argmax_coverage(["s1", "s2", "s3"], 3) == pytest.approx(1.0)


def test_argmax_coverage_empty():
    assert argmax_coverage([], 3) == 0.0


def test_reference_node_delta_basic():
    meds = {"s1": -50, "s2": -55, "ref": -70}
    # interior median = median([-50, -55]) = -52.5
    # delta = -52.5 - (-70) = 17.5
    result = reference_node_delta(meds, "ref", ["s1", "s2"])
    assert result == pytest.approx(17.5)


def test_reference_node_delta_absent():
    meds = {"s1": -50, "s2": -55}
    assert reference_node_delta(meds, "ref", ["s1", "s2"]) is None


def test_reference_node_delta_none():
    meds = {"s1": -50}
    assert reference_node_delta(meds, None, ["s1"]) is None
    assert reference_node_delta(meds, "", ["s1"]) is None
