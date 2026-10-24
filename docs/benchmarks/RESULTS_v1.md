# Benchmark results — corpus v1.0.0

Raw result files are in [`benchmarks/results/v1.0.0/`](../../benchmarks/results/v1.0.0/). Reproduce them with:

```bash
python scripts/setup_external_adapters.py
sqlninja benchmark run --dataset benchmarks/datasets/v1 --adapter native
sqlninja benchmark run --dataset benchmarks/datasets/v1 --adapter external:sql-guardrail
```

Environment for the numbers below: Windows 11, Python 3.11.9 (external tools in their own
venvs), sqlglot 30.24.0, 2026-10-24. 1,002 evaluations of 530 unique cases.

## Read this first

* **The corpus and the native engine were developed together.** Every native disagreement
  found while writing cases was triaged: either the engine was fixed or the label was
  corrected, and each correction is recorded in `IMPLEMENTATION_STATUS.md`. So the native
  score of 100% shows **consistency with the documented policy semantics**. It is *not* an
  independent measure of real-world detection. An independent, third-party corpus is needed
  for that.
* **External tools have smaller policy models.** They have no roles, labels, aggregate-only
  access or review outcomes. Our policy is translated conservatively (see
  `benchmarking/translate.py`), and each tool declares the categories it can express. The
  "within capability" column is the fairer comparison.
* **Not covered:** restricted-function and system-catalog cases are not in v1.0.0.

## Summary

| Validator | Version | Recall (all) | Precision (all) | FPR (all) | Recall (capability) | FPR (capability) | Capability cases | p50 ms | p95 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SQLGuard Ninja (native) | 0.1.0 | 100.0% | 100.0% | 0.0% | 100.0% | 0.0% | 1002 | 1.30 | 2.15 |
| sql-guardrail | 0.5.2 | 98.6% | 86.6% | 21.2% | 98.3% | 19.3% | 835 | 0.90 | 1.72 |
| agent-sql-guard | 0.2.0 | 67.9% | 86.6% | 14.5% | 89.5% | 17.2% | 759 | 0.65 | 1.26 |
| krish2105/sqlguard | 0.1.0 (git 62327f2) | 65.8% | 91.4% | 8.6% | 83.5% | 5.2% | 607 | 0.54 | 1.22 |

Latency is measured inside each validator's process around the validation call only.

## What drives the external numbers (from the per-case results)

* **sql-guardrail** has very high recall. Its false positives come from its default
  `forbid.select_star` (26), from requiring the tenant value as a literal (it rejects
  `:tenant_id` bind parameters), from not following equality chains (`s.tenant_id = o.tenant_id`)
  or `LEFT JOIN ... ON` pins (24), and from denylisted aggregate-only columns (30).
* **agent-sql-guard** has no tenant predicates by design (131 of its 187 false negatives).
  It also rejects `INTERSECT`/`EXCEPT` and `SELECT *`. Its benchmark worker works around an
  upstream bug: `PiiDenylist.from_mapping` rejects its own default when `substrings` is
  omitted.
* **krish2105/sqlguard** has no tenant predicates (131 false negatives). Its column allow-list
  cannot express aggregate-only access.
