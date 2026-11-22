# Concept of operations

FMD-CONOPS, issue 1, 2026-11-20. Who uses FlightMD, for what, around which
other systems, and where its results stop being something to rely on. Written
from the README, the walkthrough (`docs/WALKTHROUGH.md`) and the code; not yet
validated with anyone but the owner.

## 1. Purpose

After a flight, an unmanned aircraft's autopilot or ground station holds a log.
FlightMD reads that log and says, in plain words and with the evidence, what
went wrong, how serious it is and which parameter to look at. It is a
diagnostic aid for the people who fly, tune and maintain small unmanned
aircraft. It is ground software used after the flight; it flies nothing and
commands nothing.

## 2. Who uses it

| Role | Wants | Uses |
|---|---|---|
| Pilot | To know whether the last flight was healthy and what to look at before the next | Web application, one log at a time |
| Tuner | Which gain or filter to change, by how much, in a file the ground station loads | Findings, parameter sheet, tune-fly-verify |
| Maintainer | Evidence of a degrading battery, motor, sensor or airframe; a record per airframe | Airframe page: trends, maintenance log, checklist, alerts, record PDF |
| Fleet operator | The same across several airframes; to be told when something crosses a line | Airframe tags, alert webhooks, exports |
| Integrator | To run the analysis inside another product (a ground control station, a planning tool) | Python package, command line, HTTP API, report schema |
| Developer of checks | To add a check for their own hardware | Plugin entry point (`docs/plugins.md`) |
| Self-hoster | To run the service for a team on a small machine, privately | Docker Compose, configuration by environment variables |
| Project maintainer | To change parsers and rules without changing results unnoticed | Tests, corpus, this lifecycle |

## 3. Context

```
  autopilot / ground station                       firmware projects
   (PX4, ArduPilot, Betaflight,                    (published parameter
    INAV, DJI app, QGC, MP)                          metadata)
        | log file                                        | at build time,
        v                                                 v  by a script
  +-----------------------------------------------------------------+
  |  FlightMD                                                       |
  |   web application  <-- HTTP -->  API  -->  engine (library/CLI) |
  +-----------------------------------------------------------------+
     |          |             |            |               |
     v          v             v            v               v
   person    ground        other        weather,        alert
   reading   station       software     geocoding,      webhook
   a report  (parameter    (report      AI provider,    receiver
             file,         JSON,        DJI key service
             GPX/KML)      API)         (all optional, off when offline)
```

Outside systems FlightMD depends on or feeds:

- **The recorder** (autopilot, ground station or app) writes the log. Its
  accuracy and completeness are outside FlightMD.
- **Ground stations** (Mission Planner, QGroundControl) load the parameter
  file a user downloads. FlightMD never talks to a vehicle or a ground
  station itself.
- **A planning tool** (AirBrief) can give a brief hash to carry in the report
  and can read a report's track through the API.
- **Another ground application** can run the engine as a library.
- **Optional online services**: a weather archive, a geocoder, an AI provider
  (Groq or Anthropic) and DJI's key service for encrypted flight records.

Interfaces are specified in `docs/lifecycle/03-system/icd/`.

## 4. Scenarios

### 4.1 One flight

The user drops a log on the upload page (or runs `flightmd analyse`). The
format is detected from the content. The log is parsed, the armed and in-air
windows are found, the checks run, findings are explained and scored, and the
report appears: score and grade, findings most severe first with time
windows that jump to the charts and the map, parse warnings, modules that
could not be assessed, flight details, and exports. Untagged reports are gone
after an hour.

### 4.2 Tuning

A finding may carry parameter changes. The parameter sheet collects them, one
per parameter. The user downloads the sheet for their ground station, loads
it, flies, and uploads the next log with the same airframe tag.

### 4.3 An airframe over time

Tagging an upload with an airframe label keeps it. The first write returns a
token that later reads and writes need. The airframe page shows trends of
each check's headline numbers, the maintenance log and checklist, the changes
marked as applied and whether the findings behind them went away, and alert
rules that post to a webhook.

### 4.4 Inside another product

A Python caller awaits `run_analysis` and gets the report object; a script
runs the command line and reads the JSON; a service calls the HTTP API. All
three get the same report format, versioned (`docs/schema/`).

### 4.5 Hosting

One API process with an in-process queue and a SQLite file serves a small
team. More processes need Redis. Upload size, analyses at once, requests per
address and parse time are bounded by configuration. Offline mode stops every
outbound call. Contributed logs are opt-in and can be withdrawn.

## 5. Limits of use

These are the conditions the hazard assessment
(`docs/lifecycle/04-safety/hazard-assessment.md`) assumes. Outside them its
classification does not hold.

- **Advisory.** A report is one input to a person's decision. Nothing acts on
  it automatically.
- **Not a release to service.** A clean report means the checks that ran found
  nothing above their thresholds in what the log recorded. It does not mean
  the aircraft is airworthy. Checks that could not run are listed as not
  assessed; faults the log does not record cannot be found.
- **Recommendations need review.** A suggested parameter value is computed by
  a rule from one log. It is to be checked against the firmware's
  documentation and proven in a careful test flight.
- **Small unmanned aircraft.** The thresholds come from multicopters, small
  fixed-wing, VTOL and rover logs on PX4 and ArduPilot, with Betaflight, INAV
  and DJI support added later and checked on fewer logs.
- **Only what the log holds.** A low logging rate, a missing topic or a log
  cut short limits what can be found; the report says what was missing where
  it can tell.

The product does not yet show these limits to its users (safety requirement
SAF-015, proposed).
