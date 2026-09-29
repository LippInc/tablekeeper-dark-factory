# Stage 1 acceptance checks (verifier seat)

Written from `tablekeeper/spec/stage-1.md`, not from the service code. R.. and D.. name the
room plan's requirement lines and decisions. The verifier seat is the only writer of this folder.

| File | What | How to run |
|---|---|---|
| `test_s1_i1_foundation.py` | S1-I1 behaviour over HTTP | room plan recipe step 3b (`pytest /acc/test_s1_i1_foundation.py`) |
| `test_s1_i1_load.py` | S1-I1 bursts and timings | recipe step 3b, alone, with nothing else loading the service; `-rP` prints the measured values |
| `container_checks.sh` | S1-I1 image, `PORT`, health within 60 s, RUN.md command | `bash container_checks.sh <stage-dir> <name-prefix> <free-host-port>` (Git Bash, Docker, the `df-harness-runner` image) |

The pytest files use the harness fixtures (`reset`, `api`, `world`, `book`, `base_url`) and
`import fixtures as fx`. This folder holds no `conftest.py`.
