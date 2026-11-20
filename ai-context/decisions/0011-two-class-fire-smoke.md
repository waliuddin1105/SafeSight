---
id: adr-0011
type: decision
status: accepted
links: [fire_smoke, dataset_fire_smoke, quality, verification]
---
# Two-class fire/smoke detector without a person class

## Context
The approved plan declared fire_smoke classes as fire, smoke, person. The only available
trained artifact is a two-class D-Fire-style detector (names: smoke, fire; nc=2; imgsz 640)
trained outside this repository. Registry loading compares the model card classes to the
contract list and then compares the checkpoint's ordered class names to the card, so a
three-class contract rejects every two-class checkpoint regardless of card contents.
Adding a person class cannot be done without retraining: a detection head has no weights
for a class it was never trained on. Public fire/smoke sources such as D-Fire also ship no
person annotations, so the third class was already unsupported by available data.

## Options considered
Retrain on a three-class dataset with hand-annotated person boxes; amend the contract to a
two-class fire/smoke taxonomy and source person context from the pose asset and other
tasks; keep the contract and leave the artifact unusable.

## Decision
fire_smoke is a two-class detector, ordered smoke=0, fire=1. The order matches the trained
checkpoint and is the contract order used by cards, dataset data.yaml, splitting, fixtures,
reporting and model sharing. Person context is not produced by this model. At inference the
engine still builds the person list from pose detections and from any other task's person
detections, so fire alerts, growth-based hazardous_smoke decisions and event subtypes are
unchanged. Smoke that cannot be attributed to a smoking person remains uncertain_smoke and
stays reviewable rather than being suppressed.

## Consequences
Existing two-class checkpoints load without retraining or reordering. Datasets must declare
data.yaml names in the order smoke, fire and may no longer contain person labels; previously
prepared three-class datasets must be relabelled before validation. Cards and shared bundles
produced under the old three-class contract are rejected by the registry, doctor and sharing
checks. Tobacco-versus-hazardous smoke separation loses this model's person contribution and
depends on the pose asset or the cigarette_smoking model. Qualification thresholds, event
subtypes and quality gates are unaffected. This deviates from the class column of the
approved plan table and is recorded here.
