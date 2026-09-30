# Evidence record

Kept by the release clerk seat. One entry per item: the item, its unit, the commit, the
verifier's verdict and the command that proves it. Append-only within a unit; a correction is
a new entry that references the old one. Every command below runs from a clean checkout made
with the plan's environment recipe (Git Bash): `git clone --no-local -c core.autocrlf=false
-c core.eol=lf`, then the service is built from `stage-1/` and started with `--cpus 2
--memory 2g -e PORT=8080` on an `--internal` Docker network (no outbound access), and the
checks run in the organizers' `df-harness-runner` image on that network (recipe step 3b):

```
docker run --rm --network <net> -v <package>:/work:ro -v <checkout>/acceptance/stage-1:/acc:ro -w /work \
  -e PYTHONPATH=/work:/work/tablekeeper/test -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 df-harness-runner \
  python -m pytest /acc/<file> -p harness.plugin -p conftest -p no:cacheprovider \
  --import-mode=importlib --rootdir /acc --base-url http://<service>:8080 -q
```

## Unit "Stage 1: reservations"

Packaged commit: `ebbdfbd25d42d93caf3903f39e2c40b4ce48cc1b`. Acceptance checks at
`d6d301c153d49760f98037d8d6cb7cb85cef32c3`, whose `stage-1/` tree is identical to ebbdfbd's
(`git diff --quiet ebbdfbd d6d301c -- stage-1`). Packaging run `tk2-release-clerk-pkg-0930014337`,
2026-09-30. The "Result at packaging" column is the release clerk's own run of the command
against the packaged commit.

| Item | Unit | Commit | Verdict (verifier) | Proving command | Result at packaging |
|---|---|---|---|---|---|
| S1-I1 Service foundation | Stage 1: reservations | b531eff32eb99d375c512462f5d94563a8b920c7 | VERIFIED (acceptance 78dfc50) | `pytest /acc/test_s1_i1_foundation.py`, `/acc/test_s1_i1_load.py`; `bash acceptance/stage-1/container_checks.sh <stage-1> <prefix> <port>` | 103 passed; 5 passed; container checks 4 passed, 0 failed |
| S1-I2 Availability over local time | Stage 1: reservations | 69265930fef2022bb0572a45bf312af2bd561ad6 | VERIFIED (acceptance 888331a, 7dbeaf1) | `pytest /acc/test_s1_i2_availability.py`, `/acc/test_s1_i2_load.py` | 61 passed; 2 passed |
| S1-I3 Booking lifecycle | Stage 1: reservations | bb9cf3e076d399d5a4595bbb3e3963d743a8b25d | VERIFIED (acceptance 5956b62) | `pytest /acc/test_s1_i3_bookings.py`, `/acc/test_s1_i3_races.py` | 98 passed; 4 passed |
| S1-I4 Atomic reservation moves | Stage 1: reservations | 0758774adaad9057442783159e043632f6f137ec | VERIFIED (acceptance ed2493b, addendum 8a433af) | `pytest /acc/test_s1_i4_moves.py`, `/acc/test_s1_i4_races.py` | 58 passed; 2 passed |
| S1-I5 Export and import | Stage 1: reservations | 2d6207d5f72dca3d00a97b187e640bcf8865d0f6 | VERIFIED (acceptance 11eb90d); earlier REFUTED at 39e5ee0 (a non-object import body gave 400 instead of 422, D20), fixed by 2d6207d | `pytest /acc/test_s1_i5_export_import.py`, `/acc/test_s1_i5_snapshot.py`, `/acc/test_s1_i5_two_containers.py` with `-e TABLEKEEPER_SECOND_URL=http://<second container>:8080` | 36 passed; 2 passed; 1 passed |
| S1-I6 Code-quality corrections | Stage 1: reservations | a6fd03e275b09004375f3b89ae0663bbe295ecb7 | VERIFIED | plan S1-I6 commands 2–5, from `stage-1/`: vulture, pylint duplicate-code, `grep -rn "local@domain" tablekeeper`, `grep -rn "must not be empty" tablekeeper`, the R157 literal grep | commands 4–5 re-run: 1 and 1 lines; R157 grep 0 lines (commands 2–3 not re-run by the clerk) |
| S1-I7 Availability cost on a dense day | Stage 1: reservations | ebbdfbd25d42d93caf3903f39e2c40b4ce48cc1b | VERIFIED (acceptance d6d301c) | `pytest /acc/test_s1_i7_dense.py` | 5 passed |

Board check: the board (plan v2.22, "Board and commits") lists 7 items of this unit, all
`verified`; the record lists 7 items, all VERIFIED; items in the record but not on the board: 0;
items on the board but not in the record: 0.

### Packaging of "Stage 1: reservations" at ebbdfbd

- Delivery layout (task: `stage-1\` holding the service source, a Dockerfile and RUN.md, no
  nested .git): `stage-1/Dockerfile`, `stage-1/RUN.md`, `stage-1/requirements.txt`,
  `stage-1/tablekeeper/` (15 Python modules). Fresh clone: nested `.git` below the root 0,
  uncommitted or ignored files 0, CRLF files 0.
- Gate 1, build and offline start: **PASS**.
  - The build succeeded from the clean checkout, including `docker build --no-cache --pull`.
  - Healthy 1 s after `docker run` on the internal network, at `--cpus 2 --memory 2g`. Outbound from the service's network namespace fails: `[Errno 101] Network is unreachable`, and DNS fails with `Temporary failure in name resolution`.
  - First unit of work, in-network: reset 204, login 200, availability 200, booking 201, replay 200 with an identical body, read 200, overlapping booking 409 `table_unavailable`. Every request completed in ≤ 83 ms; memory 41.9 MiB of 2 GiB.
  - Negative control: the same image with a start that first fetches `https://pypi.org` exits (code 1, `URLError … Temporary failure in name resolution`) and never becomes healthy on the internal network. On the default bridge it is healthy after 1 s.
  - RUN.md's command, with only the host port changed, served `/health` 200 (container check C4).
- Checks: provided `stage_1` in-network 120 passed. Organizers' harness `--mode isolated`: `stage 1: pass` (120 passed), `stage 2: fail`, `highest contiguous stage: 1`, `claimed stage: 1 on the shipped checks`, report revision ebbdfbd. The same result in host mode.
- Reverse check (the full `stage_2` suite against the packaged service): 23 failed, 2 passed. The failures are stage-2 behaviour:
  - 22 are browser checks that time out on the UI routes `/`, `/signup`, `/login` and `/lookup`. Each of those answers 404 `not_found` JSON.
  - 1 is the combined-table booking (`table_ids`), which gives 422 instead of 201.
  - No failure is a check that could not run.
- Gate 2, no credentials, private data or unrelated files: **PASS**.
  - gitleaks v8.30.1 (`--network none`): history of all 17 commits reachable from d6d301c, and the tree: `no leaks found`.
  - Negative control: a fake `ghp_` token planted in a scratch copy is reported (`github-pat`, `leaks found: 1`).
  - Organizers' `harness check`: its credential scan reports nothing.
  - Private data: 0 user-home paths; the only email addresses are `example.com` fixtures, the seat addresses `*@factory-seats.invalid` and the operator's GitHub noreply address. Key, `.env`, database and binary files: 0.
  - Files outside `stage-1/` and `acceptance/` are the operator's setup (README.md, FACTORY.md, mandates/, factory/, .gitattributes, .gitignore).
- Organizers' structure check `python -m harness check <clone> --track tablekeeper`: `room.json is missing; …` and `1 problem(s)`. The room download is the operator's step at submission.

## Unit "Stage 2: online booking and combined tables"

Packaged commit: `1ec2f587b2713e2c3733517142929a0e7c8bdd37`. Acceptance checks at
`ac31b64bc5f472ff0ece8e5651cfe71e115185b2`, whose `stage-1/`, `stage-2/` and `design/` trees are
identical to 1ec2f58's. Design system `design/DESIGN.md` at 9069de8, the same as at 1ec2f58.
Packaging run `tk2-release-clerk-pkg2-0930070442`, 2026-09-30. The stage-2 checks run with the
stage-1 service of the same checkout as `--previous-base-url`. Load, race and upgrade files
run alone. `TABLEKEEPER_SECOND_URL` points at a second container of the stage-2 image.

| Item | Unit | Commit | Verdict (verifier; designer on screen items) | Proving command | Result at packaging |
|---|---|---|---|---|---|
| S2-I1 Carry forward and combined tables in the API | Stage 2: online booking and combined tables | bd6c9abead35821d803ad915eca66d21b6e3fb32 (copy commit 00b8caf = stage-1 at ebbdfbd) | VERIFIED (acceptance 1ea7290) | `pytest /acc/stage-2/test_s2_i1_combined.py`, `/acc/stage-2/test_s2_i1_races.py`; every `/acc/stage-1/*.py` against the stage-2 service | 64 passed; 4 passed; stage-1 acceptance 377 passed |
| S2-I2 Upgrade from stage 1 | Stage 2: online booking and combined tables | a29624e82ccbb1fce3882a0f56407bc3362363f7 | VERIFIED (acceptance 58bac83); earlier REFUTED at cb07f6d (a schema-1 record without table_id imported), fixed by a29624e | `pytest /acc/stage-2/test_s2_i2_upgrade.py` with `--previous-base-url` = stage-1 service; provided `test_sample.py::test_preceding_stage_accounts_survive_import` | 26 passed; provided stage_2 25 passed |
| S2-I3 UI shell, assets, header, signup and login | Stage 2: online booking and combined tables | 654449e3f135c7372b54dc646793797f9333c180 | VERIFIED + APPROVED (acceptance 4cca83d, d4ab607) | `pytest /acc/stage-2/test_s2_i3_shell.py`; `bash acceptance/stage-2/asset_checks.sh <stage-2>` | 30 passed; asset checks 3 passed, 0 failed |
| S2-I4 Search and availability grid | Stage 2: online booking and combined tables | a29624e82ccbb1fce3882a0f56407bc3362363f7 | VERIFIED + APPROVED (acceptance 5d9ab31, 3237495) | `pytest /acc/stage-2/test_s2_i4_grid.py` | 32 passed |
| S2-I5 Booking panel and confirmation | Stage 2: online booking and combined tables | 140dc309b39186c3c912fce3ae1ba62cb89538a1 (also verified at 869e80c, 450cf88) | VERIFIED + APPROVED (acceptance da96d65, 68c98ff) | `pytest /acc/stage-2/test_s2_i5_booking.py`, `/acc/stage-2/test_s2_i5_restaurant_list.py` | 30 passed; 5 passed |
| S2-I6 Lookup screen | Stage 2: online booking and combined tables | 1ec2f587b2713e2c3733517142929a0e7c8bdd37 | VERIFIED + APPROVED (acceptance ac31b64) | `pytest /acc/stage-2/test_s2_i6_lookup.py` | 20 passed |

Board check: the board (plan v2.31 stage 2, "Board and commits") lists 6 items of this unit,
all `verified`; the record lists 6 items, all VERIFIED; items in the record but not on the
board: 0; items on the board but not in the record: 0.

### Packaging of "Stage 2: online booking and combined tables" at 1ec2f58

- Delivery layout (task: `stage-2\` is a copy of `stage-1\` carried forward, with the service
  source, a Dockerfile and RUN.md, no nested .git):
  - `stage-2/Dockerfile`, `RUN.md`, `requirements.txt`, `tablekeeper/` (Python modules plus
    `static/` with `index.html`, `css/app.css`, 14 `js/*.js`, and 5 woff2 fonts with 2 OFL `LICENSE`
    files, byte-identical to the task's supplied fonts).
  - Fresh clone: nested `.git` below the root 0, uncommitted or ignored files 0, CRLF files 0.
  - `stage-1/` unchanged since ebbdfbd (`git diff --quiet ebbdfbd 1ec2f58 -- stage-1`).
  - `stage-2/RUN.md` is byte-identical to `stage-1/RUN.md`: its heading reads "Running
    Tablekeeper (stage 1)" and it names neither stage 2 nor the screens. Its command builds and
    starts the stage-2 service (container check C4 PASS). Reported to the architect.
- Gate 1, build, offline start and first unit of work: **PASS**.
  - The build succeeded from the clean checkout, including `docker build --no-cache --pull`.
  - Healthy 2 s after `docker run` on the internal network, at `--cpus 2 --memory 2g`. Outbound from the service's network namespace fails: `[Errno 101] Network is unreachable`, and DNS fails with `Temporary failure in name resolution`.
  - First unit of work, in-network:
    - `/`, `/signup`, `/login` and `/lookup` each answer 200 `text/html; charset=utf-8`.
    - Reset 204 and login 200; availability 200.
    - Single-table booking 201; combined-table booking 201; replay 200 with an identical body; read 200.
    - A pair member booked again gives 409 `table_unavailable`.
    - Every request completed in ≤ 64 ms; memory 60.2 MiB of 2 GiB.
  - Screens with no outbound network: `checks-2\tk2-tools\shoot.py` in the runner on the internal network, at 375 and 1280. It captured before search, signup, lookup, after search and booked, each with `no-sideways-scroll`. Result: `offsite requests: 0; problems: 0`. Every asset request went to the service's own `/assets/` (css, 14 scripts, Cormorant and Hanken Grotesk fonts).
  - Negative controls:
    - The same image with a start that first fetches `https://pypi.org` exits (code 1, `URLError … Temporary failure in name resolution`) on the internal network; on the default bridge it is healthy after 2 s.
    - The same image with an off-site font stylesheet added to the screen shell is flagged: `OFFSITE request https://fonts.googleapis.com/css2?family=Inter`, rc 1.
  - Container checks on `stage-2/`: 4 passed, 0 failed, including RUN.md's command with only the host port changed.
- Checks, in-network against the packaged image:
  - Provided `stage_1` 120 passed and `stage_2` 25 passed.
  - Acceptance `stage-1` (12 files) and `stage-2` (8 files): all passed, 0 failed.
  - Organizers' harness `--repo <clone of 1ec2f58> --stage 2 --mode isolated`: `stage 1: pass` (120), `stage 2: pass` (25), `stage 3: fail` (1 failed), `highest contiguous stage: 2`, `claimed stage: 2 on the shipped checks`, overshoot None, revision 1ec2f58. The same result in host mode.
- Reverse check (the full `stage_3` suite against the packaged stage-2, previous = a stage-2 container): 6 failed, 1 passed. Every failure is stage-3 behaviour, and no failure is a check that could not run:
  - `POST /restaurants/r_anker/policies` gives 404.
  - The availability `explain` field is missing (`KeyError: 'explain'`), in 2 checks.
  - `GET /reservations/{ref}/history` gives 404, in 2 checks.
  - Recurring-agreement adoption gives 404.
- Gate 2, no credentials, private data or unrelated files: **PASS**.
  - gitleaks v8.30.1 (`--network none`): history of all 44 commits reachable from ac31b64, and the tree: `no leaks found`.
  - Negative control: a fake `ghp_` token planted in a scratch copy of `stage-2` is reported (`github-pat`, `leaks found: 1`).
  - Organizers' `harness check`: its credential scan reports nothing.
  - Private data: 0 user-home paths. Email addresses are only `example.com` fixtures, `*@factory-seats.invalid` seat addresses and the operator's GitHub noreply address. Key, `.env`, database and archive files: 0.
  - The only binary files are the 5 supplied fonts.
  - Files outside `stage-*/`, `acceptance/` and `design/` are the operator's setup plus this record.
- Organizers' structure check `python -m harness check <clone of ac31b64> --track tablekeeper`: `room.json is missing; …` and `1 problem(s)`. The room download is the operator's step at submission.

### Re-packaging of "Stage 2: online booking and combined tables" at fa30051

This supersedes the packaging at 1ec2f58 above for this unit's delivered folder; that entry
stays as recorded. Packaged commit: `fa300514fa5d79437e30213471c72d673b6be79b` (main). It differs
from 1ec2f58 in `stage-2/RUN.md` only (`git diff --name-only 1ec2f58 fa30051 -- stage-1 stage-2
design`). This answers the RUN.md note of the 1ec2f58 packaging. The acceptance checks are those
at fa30051. Packaging run `tk2-release-clerk-pkg2-0930073357`, 2026-09-30.

| Item | Unit | Commit | Verdict (verifier) | Proving command | Result at packaging |
|---|---|---|---|---|---|
| S2-I7 RUN.md for stage 2 | Stage 2: online booking and combined tables | fa300514fa5d79437e30213471c72d673b6be79b | VERIFIED | `bash acceptance/stage-1/container_checks.sh <stage-2> <prefix> <port>` (C4 runs RUN.md's command with only the host port changed); `head -1 stage-2/RUN.md` | 4 passed, 0 failed; `# Running Tablekeeper (stage 2)` |

S2-I1..S2-I6 carry over unchanged from the entries above. At fa30051 the release clerk re-ran
every proving command listed for them, with the same counts: acceptance stage-1 377 passed;
stage-2 i1 64 + 4, i2 26, i3 30 with asset checks 3/3, i4 32, i5 30 + 5, i6 20.

Board check: the board (plan v2.35 stage 2) lists 7 items of this unit (S2-I1..S2-I7), all
`verified`; the record lists 7 items for this unit, all VERIFIED; items in the record but not on
the board: 0; items on the board but not in the record: 0.

- Delivery layout: as at 1ec2f58, with `stage-2/RUN.md` now titled "(stage 2)". It names the
  screens `/`, `/signup`, `/login` and `/lookup` and states that fonts, styles, scripts and time
  zone data are served from the image. Fresh clone: nested `.git` 0, uncommitted or ignored files
  0, CRLF files 0. `stage-1/` unchanged since ebbdfbd.
- Gate 1, build, offline start and first unit of work: **PASS**.
  - The build succeeded from the clean checkout with `docker build --no-cache --pull`.
  - Healthy 2 s after `docker run` on the internal network, at `--cpus 2 --memory 2g`. Outbound fails: `[Errno 101] Network is unreachable`, and DNS fails with `Temporary failure in name resolution`.
  - First unit of work, in-network:
    - The four screens answer 200 `text/html`.
    - Reset 204, login 200 and availability 200.
    - Single-table booking 201; combined-table booking 201; replay 200 with an identical body; read 200.
    - A pair member booked again gives 409 `table_unavailable`.
    - Every request completed in ≤ 57 ms; memory 60.2 MiB.
  - Screens at 375 and 1280 (before search, signup, lookup, after search, booked): `no-sideways-scroll`, `offsite requests: 0; problems: 0`. Every css, font and js request went to the service.
  - Negative controls:
    - The start that first fetches pypi.org exits (code 1, `URLError … Temporary failure in name resolution`) on the internal network; on the default bridge it is healthy after 1 s.
    - An off-site font stylesheet added to the shell is flagged: `OFFSITE request https://fonts.googleapis.com/css2?family=Inter` ×6.
  - Container checks on `stage-2/`: 4 passed, 0 failed. C4 runs the new RUN.md command, `docker build -t tablekeeper . && docker run --rm -e PORT=8080 -p 18601:8080 tablekeeper`: health 200.
- Checks:
  - Provided `stage_1` 120 passed and `stage_2` 25 passed.
  - Acceptance stage-1 and stage-2, file by file: all passed, 0 failed.
  - Harness `--repo <clone of fa30051> --stage 2 --mode isolated`: `stage 1: pass` (120), `stage 2: pass` (25), `stage 3: fail` (1 failed), `highest contiguous stage: 2`, `claimed stage: 2 on the shipped checks`, overshoot None, revision fa30051. The same result in host mode.
- Reverse check (the full `stage_3` suite): 6 failed, 1 passed, 0 errors. Every failure is stage-3 behaviour: policies 404, `explain` missing ×2, history 404 ×2, recurring agreement 404.
- Gate 2, no credentials, private data or unrelated files: **PASS**.
  - gitleaks v8.30.1: history of 46 commits, and the tree: `no leaks found`.
  - Negative control: a fake `ghp_` token planted in a scratch copy is reported (`github-pat`, `leaks found: 1`).
  - Private data: 0 user-home paths; no email addresses beyond `example.com`, the seat addresses and the operator's noreply. Key, `.env` and database files: 0.
  - The only binary files are the 5 supplied fonts.
- Organizers' structure check on a clone of fa30051: `room.json is missing; …` and `1 problem(s)` (rc 1). This is the operator's step at submission.
