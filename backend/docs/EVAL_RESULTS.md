# ClearanceRAG — Evaluation Results

**Generated**: 2026-07-25T11:09:45.578222+00:00

## Summary

| Metric | Value |
|---|---|
| Total Questions | 25 |
| Permission Compliance | 100.0% (25/25) |
| Boundary Cases | 100.0% (11/11) |
| Avg Faithfulness Score | 1.00 |
| Avg Retrieval Latency | 1.21ms |
| p95 Retrieval Latency | 2.03ms |

**Performance Metric:** Avg Retrieval Latency: 1.21ms \| p95 Retrieval Latency: 2.03ms

## Permission Compliance Results

| ID | Role | Boundary? | Chunks | Status | Reason |
|---|---|---|---|---|---|
| q01 | viewer | No | 3 | ✅ PASS | Returned 3 permitted chunks |
| q02 | viewer | No | 3 | ✅ PASS | Returned 3 permitted chunks |
| q03 | viewer | No | 1 | ✅ PASS | Returned 1 permitted chunks |
| q04 | manager | No | 3 | ✅ PASS | Returned 3 permitted chunks |
| q05 | viewer | No | 1 | ✅ PASS | Returned 1 permitted chunks |
| q06 | viewer | No | 3 | ✅ PASS | Returned 3 permitted chunks |
| q07 | manager | No | 3 | ✅ PASS | Returned 3 permitted chunks |
| q08 | manager | No | 2 | ✅ PASS | Returned 2 permitted chunks |
| q09 | manager | No | 2 | ✅ PASS | Returned 2 permitted chunks |
| q10 | admin | No | 3 | ✅ PASS | Returned 3 permitted chunks |
| q11 | admin | No | 3 | ✅ PASS | Returned 3 permitted chunks |
| q12 | admin | No | 3 | ✅ PASS | Returned 3 permitted chunks |
| q13 | viewer | 🔒 Yes | 0 | ✅ PASS | Correctly refused — no permitted chunks |
| q14 | viewer | 🔒 Yes | 0 | ✅ PASS | Correctly refused — no permitted chunks |
| q15 | viewer | 🔒 Yes | 0 | ✅ PASS | Correctly refused — no permitted chunks |
| q16 | viewer | 🔒 Yes | 2 | ✅ PASS | SQL filter correct — 2 permitted chunks returned (all within |
| q17 | viewer | 🔒 Yes | 2 | ✅ PASS | SQL filter correct — 2 permitted chunks returned (all within |
| q18 | manager | 🔒 Yes | 0 | ✅ PASS | Correctly refused — no permitted chunks |
| q19 | manager | 🔒 Yes | 0 | ✅ PASS | Correctly refused — no permitted chunks |
| q20 | manager | 🔒 Yes | 0 | ✅ PASS | Correctly refused — no permitted chunks |
| q21 | admin | No | 1 | ✅ PASS | Returned 1 permitted chunks |
| q22 | admin | No | 3 | ✅ PASS | Returned 3 permitted chunks |
| adv_01 | viewer | 🔒 Yes | 0 | ✅ PASS | Correctly refused — no permitted chunks |
| adv_02 | superadmin | 🔒 Yes | 0 | ✅ PASS | Correctly refused — no permitted chunks |
| adv_03 | None | 🔒 Yes | 0 | ✅ PASS | Correctly refused — no permitted chunks |

## Faithfulness Results

| ID | Role | Score | Found | Missing |
|---|---|---|---|---|
| q01 | viewer | 1.0 | 9 AM to 6 PM, Monday through Friday | — |
| q02 | viewer | 1.0 | 15 days | — |
| q03 | viewer | 1.0 | 4 meters | — |
| q04 | manager | 1.0 | 8 km/h | — |
| q05 | viewer | 1.0 | 90 days | — |
| q06 | viewer | 1.0 | 2-3 business days | — |
| q07 | manager | 1.0 | 1.2 million | — |
| q08 | manager | 1.0 | 3.8M | — |
| q09 | manager | 1.0 | 78% | — |
| q10 | admin | 1.0 | $2.8M, salary | — |
| q11 | admin | 1.0 | $450M | — |
| q12 | admin | 1.0 | $1.1B | — |
| q13 | viewer | N/A | — | — |
| q14 | viewer | N/A | — | — |
| q15 | viewer | N/A | — | — |
| q16 | viewer | N/A | — | — |
| q17 | viewer | N/A | — | — |
| q18 | manager | N/A | — | — |
| q19 | manager | N/A | — | — |
| q20 | manager | N/A | — | — |
| q21 | admin | 1.0 | 82% | — |
| q22 | admin | 1.0 | 2012, 2,500 | — |
| adv_01 | viewer | N/A | — | — |
| adv_02 | superadmin | N/A | — | — |
| adv_03 | None | N/A | — | — |

---

> **Note**: Permission compliance is enforced at the database layer via
> `WHERE dc.min_role_level <= :user_role_level`. The eval harness tests
> this filter directly against the seeded synthetic corpus.