# Sample logs for manual/integration testing

This directory intentionally ships empty. The PX4 ULog integration tests in
`test_ulog_parser.py` (`@pytest.mark.integration`) skip automatically when no
sample file is present — this is expected in CI.

To verify the multi-format parsers against **real** flight data before
relying on them, source sample logs from:

- **PX4 ULog (.ulg)** — https://review.px4.io has downloadable sample logs,
  or fly a PX4 vehicle in SITL (`make px4_sitl gazebo`) and copy the log from
  `~/.ros/log` or the simulator's `build/px4_sitl_default/logs/` directory.
- **ArduPilot dataflash (.bin)** — https://ardupilot.org/planner/docs/common-downloading-and-analyzing-data-logs-in-mission-planner.html
  describes downloading logs via Mission Planner; ArduPilot's SITL
  (`sim_vehicle.py`) also produces real `.bin` logs locally.
- **MAVLink telemetry (.tlog)** — QGroundControl and Mission Planner both
  write a `.tlog` automatically to their default log directory during any
  GCS-connected flight (simulated or real).

Drop a sample file here (e.g. `sample.bin`, `sample.tlog`) and run:

```bash
pytest tests/test_ulog_parser.py -m integration -v
```

**Before trusting `ardupilot_parser.py` or `mavlink_telemetry_parser.py` in
production**, run each against a real sample and manually compare a few
findings against what Mission Planner / QGroundControl / Flight Review shows
for the same flight — the field-name and unit-conversion assumptions in
those two parsers are verified against pymavlink's dialect definitions, not
against real recorded data, and ArduPilot field names vary across firmware
versions. The EKF analyser is intentionally not wired up for these two
formats yet (see the module docstrings) — that mapping needs real-log
verification before it's safe to add.
