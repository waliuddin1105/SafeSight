---
id: fire_smoke
type: use_case
status: implemented
links:
- architecture
- quality
- dataset_fire_smoke
- adr-0011
- adr-0015
---
# Fire Smoke

fire_smoke is independently trainable and replaceable. Its taxonomy and collection contract are in datasets/fire_smoke/README.md; recipes and quality targets are in training/fire_smoke/config.yaml. It does not import another use-case trainer.

The default recipe trains the curated corpus at `datasets/fire_smoke_curated` for at most 50 epochs with patience 8. Qualification remains a separate real-video gate.
