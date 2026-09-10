---
name: test-cleanup-safety
description: Never blanket-delete tables that hold real data in throwaway tests; scope cleanup to test-created rows only
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9f74b873-0a04-4bea-ae35-74d4cc5d70ca
---

When writing throwaway verification scripts against the LIVE penggilingan DB, cleanup MUST delete only rows the test itself created — identify them by a unique marker (temp supplier name like `__TMP_X__`, temp kode prefix, or captured ids). NEVER issue blanket deletes on shared tables.

**Why:** On 2026-07-02 a test cleanup ran `DELETE FROM silo_storage WHERE silo_id IN (<G1 silos>)` and `UPDATE silos SET status='kosong'`, which wiped the user's REAL silo_storage record (LOT-20260702-01 in Silo A) and emptied the silo. Had to reconstruct the row by hand. Real data lives in the same tables as test data.

**How to apply:**
- Track created ids explicitly and delete by those ids, or filter by the temp supplier/kode marker.
- Never `DELETE FROM <table> WHERE <shared_fk> IN (...)` or reset status on rows the test didn't create.
- Prefer creating a fully isolated temp scope (temp warehouse/silo) when a test must exercise a shared resource — or better, run destructive tests against a scratch DB, not the live one.
- Before any DB-mutating test, remember the user has real rows: GB-20260702-01/02 (Catur), LOT-20260702-01 (in Silo A). See [[penggilingan-beras-project]].
