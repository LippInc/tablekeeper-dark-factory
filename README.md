# Tablekeeper, built by a six-seat dark factory

Entry for the WeAreDevelopers x BAND "Dark Factory" hackathon, track **Tablekeeper** (a restaurant reservation service built over four stages).

Team: LippInc.

Six Claude Code seats in one Band Desktop room built everything under `stage-*`, `acceptance/`, `design/` and the evidence record. The only human input during the run was one task per stage. The factory itself (seats, loop, design choices, what failed, time and cost) is described in [FACTORY.md](FACTORY.md).

This repository is the factory's second full run. The first run reached stage 3 and stopped in stage 4 when its Band room hit the per-room message limit; what that taught the factory is in FACTORY.md.

## How to read this repository

| Path | What it is | Who wrote it |
|---|---|---|
| `FACTORY.md` | The factory: seats, the loop, how it stays hands-off, stand-up steps, failures and measured cost | the team |
| `mandates/` | One generic mandate per seat, named after the seat as the room shows it; each starts with its harness and model | the team |
| `factory/` | The stand-up script (Windows PowerShell, with a bash twin for macOS and Linux) and its known-bad tests, the workspace templates the seats get, and read-only watchers for the room | the team |
| `room.json` | The full room, downloaded from Band Desktop unchanged | Band Desktop |
| `stage-1/` ... `stage-4/` | One complete service per stage (`Dockerfile`, `RUN.md`, source), each carried forward from the previous stage and extended | builder |
| `acceptance/stage-N/` | The verifier's own checks, written from each stage's specification and calibrated against a known-bad | verifier |
| `design/` | The design system the builder follows and the designer reviews against | designer |
| `EVIDENCE.md` | Verdicts, gates and the reverse check for each item and stage | release clerk |

Every commit names the seat that made it (author name = seat) and starts with the unit and item it belongs to, so the git log and the room can be read side by side.

## Run a stage

Each stage folder is a service on its own: follow its `RUN.md`. To grade a folder the way judges do, from the organizers' package:

```
python -m harness run --track tablekeeper --repo <this repository> --stage N --mode isolated --out <new folder>
```
