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
