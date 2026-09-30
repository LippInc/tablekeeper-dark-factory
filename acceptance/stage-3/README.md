# Stage 3 acceptance checks (verifier seat)

Written from `tablekeeper/spec/stage-3.md`, not from the service code. R.., H.. and P.. name the
room plan's requirement lines and decisions. The verifier seat is the only writer of this folder.

| File | What | How to run |
|---|---|---|
| `test_s3_i1_policies.py` | S3-I1 policies: the endpoint's 401/404/403/201, replay and reuse, keyed-write basics and the D2 path scope (S3N-3), versions per restaurant, the P1/P7 validation matrix (each 422, no version allocated) and the accepted range bounds, unknown fields changing no restaurant setting, the public list in publication order without policy 0 (P8), the detail unchanged, `manager_user_ids` at reset (P6), selection by local start date (past dates, ties to the greatest version, policy 0 before any), availability and booking under the selected policy (R305) | recipe S3-2 (`chk s2 /acc/stage-3/test_s3_i1_policies.py -p conftest --import-mode=importlib --rootdir /acc`) |
| `test_s3_i1_terms.py` | S3-I1 terms and revisions: `revision` and `accepted_terms` on every reservation response, cancel at the next revision freeing the table, seeded bookings, old receipts, a publication changing no accepted booking, the accepted cutoff for cancel, PATCH and move (B1), real, no-op, reversed-pair and failed amendments, `expected_revision` (H3, P10), moves per item, a pair's summed policy capacity, the owner-only decision, each booking's own duration after every writer (B2) | recipe S3-2, as above |
| `test_s3_i1_races.py` | S3-I1 races: one policy key from 20 clients, 20 amendments with one revision (three rounds), 20 publications racing 20 creates (versions 1..20, whole terms), and the S1-I7 dense day under two durations at 50 in flight | recipe S3-2, alone, with nothing else loading the service; `-rP` prints the measured values |
| `test_s3_i1_upgrade.py` | S3-I1 upgrade in stage-3 shape: a stage-1 export imported into stage 3 keeps sessions, passwords, references (revision 1, policy 0, decision), receipts, fresh references and the E10 stray `table_ids` | recipe S3-2: needs `TABLEKEEPER_STAGE1_URL` (the stage-1 service of the same checkout); run alone against other files that reset the stage-1 service |

The pytest files use the harness fixtures (`reset`, `api`, `anon`, `base_url`) and
`import fixtures as fx`; `test_s3_i1_upgrade.py` reuses the stage-1 world builder of
`../stage-2/test_s2_i2_upgrade.py`. This folder holds no `conftest.py`.

## Earlier checks superseded under H8

`acceptance/stage-1/` and `acceptance/stage-2/` run unchanged against the `stage-3/` service. A
check that asserts a shape the stage-3 specification changes is listed here with the stage-3
line that supersedes it and its stage-3 replacement, and is deselected in that run; every other
failure is a regression. Each listed check was shown to fail only on the added fields: on a
throwaway service that renders reservations without `revision` and `accepted_terms`, all seven
pass (S3-I1, 388df81).

Deselect list (pass each as `--deselect <node id>`):

| Node id | Superseded by (stage-3 specification) | Stage-3 replacement |
|---|---|---|
| `acceptance/stage-1/test_s1_i3_bookings.py::test_cancel_answers_the_cancelled_booking_and_frees_the_table` | R330 "Every reservation response gains `revision` (1 at creation) and `accepted_terms`"; R337 "Cancel increments revision once; repeated cancel does not." | `test_s3_i1_terms.py::test_cancel_answers_the_cancelled_booking_at_the_next_revision_and_frees_the_table` |
| `acceptance/stage-2/test_s2_i2_upgrade.py::test_sessions_from_stage_1_stay_signed_in` | R330; "Seeded bookings start at revision 1 under policy 0" (H6: imported bookings likewise) | `test_s3_i1_upgrade.py::test_sessions_from_stage_1_stay_signed_in` |
| `acceptance/stage-2/test_s2_i2_upgrade.py::test_stage_1_passwords_log_in_after_the_upgrade` | R330; H6 | `test_s3_i1_upgrade.py::test_stage_1_passwords_log_in_after_the_upgrade` |
| `acceptance/stage-2/test_s2_i2_upgrade.py::test_stage_1_references_read_the_same_with_table_ids` | R330; H6 | `test_s3_i1_upgrade.py::test_stage_1_references_read_in_stage_3_shape` |
| `acceptance/stage-2/test_s2_i2_upgrade.py::test_every_stage_1_receipt_replays_its_original_body` | R330 (its closing list comparison); the replays themselves still return the original stage-1 bodies (R332) | `test_s3_i1_upgrade.py::test_every_stage_1_receipt_replays_its_original_body` |
| `acceptance/stage-2/test_s2_i2_upgrade.py::test_new_references_do_not_collide_with_imported_ones` | R330; H6 | `test_s3_i1_upgrade.py::test_new_references_do_not_collide_with_imported_ones` |
| `acceptance/stage-2/test_s2_i2_upgrade.py::test_a_stray_table_ids_field_in_a_stage_1_reservation_is_ignored` | R330; H6 | `test_s3_i1_upgrade.py::test_a_stray_table_ids_field_in_a_stage_1_reservation_is_ignored` |
