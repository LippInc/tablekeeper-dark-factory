# Stage 2 acceptance checks (verifier seat)

Written from `tablekeeper/spec/stage-2.md`, not from the service code. R.. and E.. name the
room plan's requirement lines and decisions. The verifier seat is the only writer of this folder.

| File | What | How to run |
|---|---|---|
| `test_s2_i1_combined.py` | S2-I1 combined tables in the API: fixture `combinable` and seeded `status`/`table_ids` (E4), `available_options` (R256/R257), `table_ids` on create, PATCH and move items in E3 order, reversed pairs (E2), response shapes, cancel, table-set occupancy after every writer, receipts, schema-2 export/import | recipe S2-2 (`chk /acc/stage-2/test_s2_i1_combined.py -p conftest --import-mode=importlib --rootdir /acc`) |
| `test_s2_i1_races.py` | S2-I1 races on pairs at 50 in flight and the S1-I7 dense day with 20 declared pairs | recipe S2-2, alone, with nothing else loading the service; `-rP` prints the measured values |
| `test_s2_i2_upgrade.py` | S2-I2 upgrade: a stage-1 export (sessions, accounts, bookings, receipts of `/reservations` and `/reservation-moves`, a lost response, a failed key) imported into stage 2; a stage-2 export with pairs into a second stage-2 container; invalid imports (D20, E10) | recipe S2-2: needs `--previous-base-url` (the stage-1 service of the same checkout) and `TABLEKEEPER_SECOND_URL` (a second stage-2 container); `-rP` prints how many replays were also byte-identical |

The pytest files use the harness fixtures (`reset`, `api`, `anon`, `base_url`, `previous_api`) and
`import fixtures as fx`. This folder holds no `conftest.py`.

## Stage-1 checks superseded under G6

`acceptance/stage-1/` runs unchanged against the `stage-2/` service. A stage-1 check that asserts
a shape the stage-2 specification changes is listed here with the stage-2 line that supersedes it
and is deselected in that run; every other failure is a regression.

Deselect list (pass each as `--deselect <node id>`): none so far. At S2-I1 (bd6c9ab) every stage-1
acceptance check passed against `stage-2/`.
