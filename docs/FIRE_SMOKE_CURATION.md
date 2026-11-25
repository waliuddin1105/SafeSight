# Fire/smoke curated corpus

The curated corpus combines pinned, unaugmented public detector exports with a balanced
D-Fire replay subset. It never treats unreviewed model predictions as ground truth and
never starts training.

## Commands

Set `ROBOFLOW_API_KEY` in the ignored `.env`, then run:

```powershell
.\.venv\Scripts\python.exe tools\prepare_fire_smoke_curated.py preflight
.\.venv\Scripts\python.exe tools\prepare_fire_smoke_curated.py download
.\.venv\Scripts\python.exe tools\prepare_fire_smoke_curated.py target-review
.\.venv\Scripts\python.exe tools\prepare_fire_smoke_curated.py prelabel-target
.\.venv\Scripts\python.exe tools\prepare_fire_smoke_curated.py build
```

Downloads resume under `datasets/_downloads/fire_smoke_curated/`. The finalized training
folder is `datasets/fire_smoke_curated/`; suspicious records and contact sheets are under
`artifacts/fire-smoke-curation/audit/`. Source archives and generated corpora are ignored by Git.

Target frames extracted from uploaded SafeSight tests remain under
`artifacts/fire-smoke-curation/target_review/` with status `REVIEW_REQUIRED`. Empty labels
there mean “not reviewed,” not “verified negative.” They are never copied into the corpus
automatically.

After the corpus passes validation, training on another machine uses:

```powershell
.\.venv\Scripts\python.exe tools\validate_dataset.py fire_smoke --root datasets/fire_smoke_curated
.\.venv\Scripts\python.exe training\fire_smoke\train.py --config training/fire_smoke/config.curated.yaml
```

Both the default and curated fire/smoke recipes use this corpus. Training runs for at most
50 epochs with early-stopping patience 8. The best validation checkpoint is retained.

The preparation report describes structural and annotation-policy checks only. Model quality
must be measured on source-separated real footage after training.
