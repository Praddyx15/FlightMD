# Flight-dynamics checks low-level design

FMD-LLD-DYN, issue 1, 2026-11-22.

As built. Requirements: `05-requirements/hlr-dyn.sdoc`, `05-requirements/llr-dyn.sdoc`. The framework the
checks run in is in `lld-anl.md`; the thresholds below are copied from the code and the LLR are the
requirement (RS-18).

## 1 Purpose and code

| File | Check | Weight | LLR |
|---|---|---|---|
| `analysers/oscillation.py` | Rate-loop oscillation from the angular-rate spectrum | 20 | 001..019 |
| `analysers/vibration.py` | Vibration level, clipping, IMU errors and disagreement | see the class | 020..037 |
| `analysers/ekf.py` | Estimator innovation flags, solution bits, test ratios, wind | see the class | 038..054 |
| `analysers/ascent_profile.py` | Rocket-style ascent, apogee and recovery deployment | 0 | 055..065 |

## 2 Structure and data flow

```
oscillation: vehicle_angular_velocity -> per gap-free stretch, 4 s Welch windows (resampled)
             -> per axis worst sustained peak in 1 Hz .. min(100 Hz, Nyquist) -> level -> finding
             -> gain advice by band (below 12 Hz rate P, 12-35 Hz D, above 35 Hz mechanical)
vibration:   vehicle_imu_status metric > autopilot vibration topic > raw accelerometer (high-pass, 1 s RMS)
             -> 95th percentile level; clip counters or plateau clips; IMU error counters; IMU mismatch
ekf:         armed rows -> innovation flags, solution bits (by source), ArduPilot faults and timeouts
             -> test ratios above 1.0 (rejected) or above 0.8 for 2 s (near limit) -> wind jump
ascent:      GPS altitude -> one prominent apogee (>= 300 m, or a launch above 2.5 g) -> boost
             stability -> descent rate and deployment point
```

## 3 Thresholds

| Check | Threshold | Value | LLR |
|---|---|---|---|
| Oscillation | Amplitude mild / moderate / severe | 5 / 15 / 40 deg/s | 009 |
| Oscillation | Peak prominence at least | 25 (`MIN_PROMINENCE`) | 009 |
| Oscillation | Band limits for the advice | 12 Hz, 35 Hz | 014, 015 |
| Oscillation | Lowest usable sample rate | 10 Hz | 002 |
| Vibration | Clip counter warning | 100 | 032 |
| Vibration | IMU error counter at least | 10 | 029 |
| EKF | Test ratio rejected / near limit for 2 s | 1.0 / 0.8 | 048, 049 |
| EKF | Wind change | 5.0 m/s | 050 |
| Ascent | Qualifying apogee / launch acceleration | 300 m / 2.5 g | 058, 060 |
| Ascent | Asymmetric boost (coefficient of variation) | 0.6 | 061 |
| Ascent | Low deployment: below share of apogee | 0.1 | 063 |

The vibration level bands differ by source (PX4 metric, ArduPilot VIBE 30 and 60 m/s^2, raw accelerometer);
they are in LLR-DYN-024 to 028. Sources of the numbers: the PX4 bands follow the PX4 Flight Review
thresholds and the ArduPilot bands the ArduPilot vibration guidance, both to confirm; the others are the
code author's choices (OI-006).

## 4 Error handling

As in `lld-anl.md`: an exception becomes a skipped result. A check that has no usable data skips with the
reason (oscillation below 10 Hz or too short; no vibration source; no estimator data while armed; no
qualifying ascent profile).

## 5 Resource use and limits

The spectrogram is the heaviest step: one FFT per 4 s window per axis. Chart data is held to at most 512
frequency bins (`CHART_MAX_BINS`) and downsampled time series.

## 6 Known gaps and deviations

| Gap | Reference |
|---|---|
| The ascent profile check has weight 0 and is never scored | LLR-DYN-055 |
| A plugin's weight is added unscaled, which moves every other module's share | PR-037 |
| No real log of a rocket or balloon flight in the corpus | OI-015 |
