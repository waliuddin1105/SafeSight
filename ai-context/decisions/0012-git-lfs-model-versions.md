---
id: adr-0012
type: decision
status: accepted
links: [artifacts, deployment, quality, adr-0006]
---
# Git LFS for immutable model versions

## Context

The shared-drive bundle workflow preserved integrity but required an extra manual transfer.
A contributor pulled the application on another Windows device and received raw missing-card
paths because Git intentionally excluded both the imported model card and its 120 MB weight.
Relative path resolution was correct, but the artifact was not present on that device.

## Options considered

Continue manual bundles only; use DVC with a separately configured remote; publish release
assets and maintain a download manifest; or store immutable version weights in Git LFS while
keeping cards in normal Git.

## Decision

Track supported binaries below `models/SLUG/versions/RUN_ID/` with Git LFS and track their
model cards as normal text. Keep datasets, pretrained starting assets, generated artifacts,
secrets and active root cards out of version control. Preserve the checksum-verified bundle
CLI as the offline/shared-drive fallback. Missing active artifacts produce portable,
actionable health states rather than operating-system paths. Installed unqualified versions
are discoverable for explicit evaluation but are never activated automatically.

## Consequences

Each contributor must install Git LFS and run `git lfs pull`. GitHub LFS quotas and access
must be monitored. A card and its LFS pointer must be committed together, and the card hash
must match the materialized bytes. Clones without LFS objects cannot run the model but now
receive a clear missing-artifact status. Production activation and qualification rules are
unchanged. ADR 0006 remains authoritative for colocated training recipes and the bundle
format, but its shared-drive-only binary-sharing choice is superseded.
