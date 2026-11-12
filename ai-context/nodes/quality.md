---
id: quality
type: component
status: implemented
links:
- adr-0009
- adr-0008
- architecture
---
# Quality

## What, why and how

Model and event gates distinguish structural errors, insufficient data, undefined metrics and failed targets. Validation has minimum positive/negative/group support; hidden-cigarette support is checked separately.

## Inputs and outputs

Input: frozen model/image metrics, cached video predictions and provenance. Output: calibrated thresholds, grouped CIs, PR curves, failure diagnoses and PASS/FAIL.

## Gotchas

Synthetic/untrained artifacts cannot pass. Object-size AP50 reports absent size/class bins as undefined. Joint fusion is measured separately from independent training.

Image training and frozen qualification are separate commands; see docs/IMPROVEMENTS.md and ADR 0008.

Validation-only comparison and measured failure galleries are implemented; see ADR 0009.
