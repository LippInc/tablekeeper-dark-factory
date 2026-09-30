# Stage 4 acceptance checks (verifier seat)

Written from `tablekeeper/spec/stage-4.md`, not from the service code. R.., J.. and Q.. name the
room plan's requirement lines and decisions. The verifier seat is the only writer of this folder.

| File | What | How to run |
|---|---|---|
| `test_s4_i1_revision.py` | S4-I1 the restaurant revision, read through the schema-4 export: 0 after a reset with seeded bookings; +1 exactly once per successful create (single, pair), adoption of four, real PATCH, move batch with two real changes, cancel and policy publication, the other restaurant unchanged; +0 for no-ops (same values, only `expected_revision`, a reversed pair, a batch of no-op items, a repeated cancel), failures (create 409/422/401, publication 403/422, PATCH stale/conflict/another owner's, a failed batch, a failed and a second adoption) and replays (create, publication, move, adoption); a stage-4 import keeps it, an earlier stage's export (stage 3, 2, 1) imports at 0, an invalid exported revision is 422; the stage-4 replacements of the two stage-3 checks below | recipe S4-2 (`chk s3 /acc/stage-4/test_s4_i1_revision.py -p conftest --import-mode=importlib --rootdir /acc`): needs `TABLEKEEPER_SECOND_URL`, `TABLEKEEPER_STAGE3_URL`, `_STAGE2_URL`, `_STAGE1_URL`; resets them: run alone against other files that reset them |
| `test_s4_i1_races.py` | S4-I1 twenty simultaneous creates, two on each of ten tables, three rounds: exactly ten 201s and the revision up by ten | recipe S4-2, alone, with nothing else loading the service; `-rP` prints the outcomes |

The pytest files use the harness fixtures (`reset`, `api`, `anon`, `base_url`) and
`import fixtures as fx`; `test_s4_i1_revision.py` reuses the stage-3 world of
`../stage-3/test_s3_i5_import.py`. This folder holds no `conftest.py`.

## Earlier checks superseded in stage 4

`acceptance/stage-1/`, `acceptance/stage-2/` (with the deselect list in `../stage-3/README.md`)
and `acceptance/stage-3/` run unchanged against the `stage-4/` service. A check that asserts a
value a stage-4 rule changes is listed here with the rule and its stage-4 replacement, and is
deselected in that run; every other failure is a regression. Each listed check was shown to fail
only on that value: a throwaway copy differing only in the asserted schema number (4 instead of
3; 5 as the unknown schema) passes (S4-I1, b9c3881).

Deselect list: pass each node id as `--deselect <node id>`. Node ids are relative to the pytest
rootdir, the acceptance folder (the recipe's `--rootdir /acc`).

| Node id | Superseded by | Stage-4 replacement |
|---|---|---|
| `stage-3/test_s3_i5_import.py::test_a_stage_3_export_restores_unchanged_in_another_stage_3` | Q24/J6 "Export schema 4 adds per restaurant `revision` …": the export's `schema` is 4, not 3 | `test_s4_i1_revision.py::test_a_stage_4_export_restores_unchanged_in_another_stage_4` |
| `stage-3/test_s3_i5_import.py::test_an_invalid_stage_3_export_is_refused_and_changes_nothing[schema_4]` | Q24/J6: schema 4 is the current schema, so an export of schema 4 is valid | `test_s4_i1_revision.py::test_an_export_of_an_unknown_schema_is_refused[5]` |
