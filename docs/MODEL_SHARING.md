# Sharing trained models

Use a shared drive for versioned model ZIP bundles. Commit source/configuration and
documentation to Git; keep datasets and binary models outside Git. No LFS or DVC
setup is required. A shared-folder location/account is chosen by your team outside
the application; no credentials or uploads are managed by SafeSight.

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

Only weights/card are bundled; training reports and dataset provenance remain on
the training computer unless separately shared. No real trained weights exist yet,
so transfer checks use inert synthetic files. Remote HTTPS transfer remains unverified.
