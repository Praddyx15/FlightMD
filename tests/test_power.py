"""
Tests for PowerAnalyser — board voltage and peripheral over-current.
"""

import numpy as np
import pandas as pd

from flightmd_core.analysers.power import PowerAnalyser
from flightmd_core.models.findings import Severity


def power(n: int = 300, vcc=5.1, **cols) -> pd.DataFrame:
    df = pd.DataFrame({"timestamp": np.arange(n) * 100_000, "voltage5v_v": vcc})
    for k, v in cols.items():
        df[k] = v
    return df


def run(topics):
    return PowerAnalyser().safe_analyse(topics, {})


def test_steady_supply_is_clean():
    result = run({"system_power": power()})
    assert not result.skipped
    assert result.findings == []
    assert result.key_metrics["min_vcc_v"] == 5.1


def test_brownout_dip_is_critical():
    vcc = np.full(300, 5.1)
    vcc[100:105] = 4.1
    [f] = run({"system_power": power(vcc=vcc)}).findings
    assert f.kind == "power.vcc_out_of_range"
    assert f.severity == Severity.CRITICAL
    assert f.t_start_s == 10.0


def test_usb_bench_time_is_ignored():
    vcc = np.full(300, 5.1)
    vcc[:50] = 4.0
    usb = np.zeros(300)
    usb[:50] = 1
    assert run({"system_power": power(vcc=vcc, usb_connected=usb)}).findings == []


def test_mavlink_power_flags():
    flags = np.full(300, 1)            # brick valid
    flags[200:210] |= 8                # peripheral over-current
    [f] = run({"system_power": power(power_flags=flags)}).findings
    assert f.kind == "power.overcurrent"


def test_usb_flag_hides_low_voltage():
    flags = np.full(300, 4)
    assert run({"system_power": power(vcc=4.0, power_flags=flags)}).findings == []


def test_only_armed_time_counts():
    vcc = np.full(300, 5.1)
    vcc[:20] = 4.0
    status = pd.DataFrame({"timestamp": [0, 5_000_000], "arming_state": [1, 2]})
    assert run({"system_power": power(vcc=vcc), "vehicle_status": status}).findings == []


def test_unweighted():
    assert PowerAnalyser.weight == 0.0


def test_missing_topic_skips():
    result = run({})
    assert result.skipped
    assert "system_power" in result.skip_reason
