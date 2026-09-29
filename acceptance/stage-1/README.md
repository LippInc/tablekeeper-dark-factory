# Stage 1 acceptance checks (verifier seat)

Written from `tablekeeper/spec/stage-1.md`, not from the service code. R.. and D.. name the
room plan's requirement lines and decisions. The verifier seat is the only writer of this folder.

| File | What | How to run |
|---|---|---|
| `test_s1_i1_foundation.py` | S1-I1 behaviour over HTTP | room plan recipe step 3b (`pytest /acc/test_s1_i1_foundation.py`) |
| `test_s1_i1_load.py` | S1-I1 bursts and timings | recipe step 3b, alone, with nothing else loading the service; `-rP` prints the measured values |
| `test_s1_i2_availability.py` | S1-I2 availability over local time | recipe step 3b |
| `test_s1_i2_load.py` | S1-I2 dense day, alone and 50 in flight | recipe step 3b, alone; `-rP` prints the measured values |
| `test_s1_i3_bookings.py` | S1-I3 create, idempotency, reads, cancel, PATCH, listed slots bookable | recipe step 3b |
| `test_s1_i3_races.py` | S1-I3 the four races at 50 in flight | recipe step 3b, alone; `-rP` prints the measured values |
| `test_s1_i4_moves.py` | S1-I4 atomic reservation moves | recipe step 3b |
| `test_s1_i4_races.py` | S1-I4 move-key replay race and mixed race on one table | recipe step 3b, alone; `-rP` prints the measured values |
| `test_s1_i5_export_import.py` | S1-I5 export and import on one service | recipe step 3b |
| `test_s1_i5_two_containers.py` | S1-I5 export from one container, import into a second | recipe step 3b with `-e TABLEKEEPER_SECOND_URL=http://<second container>:8080` (a second `docker run` of the same image on the run's network); fails without it |
| `test_s1_i5_snapshot.py` | S1-I5 export under concurrent writes; export and import under 10 s | recipe step 3b, alone; `-rP` prints the measured values |
| `container_checks.sh` | S1-I1 image, `PORT`, health within 60 s, RUN.md command | `bash container_checks.sh <stage-dir> <name-prefix> <free-host-port>` (Git Bash, Docker, the `df-harness-runner` image) |

The pytest files use the harness fixtures (`reset`, `api`, `world`, `book`, `base_url`) and
`import fixtures as fx`. This folder holds no `conftest.py`.
