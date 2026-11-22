# Sharing trained models

Immutable versioned model cards are stored in normal Git and their large weight files
are stored with Git LFS. This keeps every contributor's `models/SLUG/versions/RUN_ID`
layout identical without committing large binaries as ordinary Git objects. Datasets,
pretrained starting assets, active root cards and runtime artifacts remain outside LFS.

Install Git LFS once on every development/training device, then clone or pull normally:

```text
git lfs install
git pull --ff-only
git lfs pull
```

Before committing a newly trained or imported version, keep its weights and card together
under `models/SLUG/versions/RUN_ID/`. Confirm the binary is LFS-managed:

```text
git check-attr filter -- models/SLUG/versions/RUN_ID/best.pt
git lfs status
```

The filter must be `lfs`. Commit the card and LFS pointer together. Never commit a card
whose artifact is absent, outside its immutable version directory, or has a different
SHA-256. GitHub LFS storage/bandwidth limits apply; repository owners must monitor them.

The dashboard lists installed inactive versions for explicit video testing. Missing
production activation is reported without machine-specific absolute paths. An unqualified
version remains evaluation-only even when its LFS object is present.

## Offline/shared-drive fallback

The checksum-verified ZIP workflow remains available when Git LFS access is unavailable.
Use a trusted shared drive for the bundle; no credentials or uploads are managed by
SafeSight.

On the training computer, export an existing run:

```text
python tools/share_model.py export cigarette_smoking RUN_ID --output F:/Shared/SafeSight/cigarette_smoking-RUN_ID.zip
```

The ZIP contains the exact version's weights and model card plus per-file checksums.
The command also writes a .zip.sha256 sidecar and prints the bundle checksum.
Share the ZIP and its checksum through your trusted team drive. Use unique version
names; exports refuse to overwrite existing bundles.

On a teammate's computer, install it:

```text
python tools/share_model.py fetch F:/Shared/SafeSight/cigarette_smoking-RUN_ID.zip --sha256 CHECKSUM
```

A direct HTTPS download URL can replace the file path. For authenticated cloud
drives, use the drive's local sync folder or download the ZIP through its authorized
interface first. The tool never bypasses login pages. Both commands accept
--models-root PATH **before** export/fetch; the default is MODELS_ROOT from .env.

The tool checks the bundle, model card, class order and artifact checksum, then
atomically installs models/SLUG/versions/RUN_ID. An identical version is reused;
a conflicting existing version is preserved and rejected. It does not execute model
files or activate them. Synthetic/FAIL metadata stays intact.

Review the card, then select a passing real-data run explicitly:

```text
python tools/activate_model.py cigarette_smoking RUN_ID
```

Failed/synthetic candidates require --evaluation and runtime EVALUATION_MODE=true.
Restart the worker after activation. Install the registered pretrained context
assets separately using tools/fetch_pretrained.py; the pose asset must match the
card's context_asset_sha256 when specified. Model transfer does not establish
accuracy or replace joint smoking/fire fusion evaluation.

Weights/card, available training_config.json/training_report.json, and matching qualification
attestations are bundled; detailed qualification galleries and dataset provenance remain on
the training computer unless separately shared. No real trained weights exist yet,
so transfer checks use inert synthetic files. Remote HTTPS transfer remains unverified.

Transferred recipes support later qualification with local data. Qualification uses the frozen card temporal policy and the receiving model root for preprocessing assets. Relative paths remain rooted in the receiving checkout.
