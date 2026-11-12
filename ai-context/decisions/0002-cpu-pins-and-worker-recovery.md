---
id: adr-0002
type: decision
status: accepted
links: [dependencies, worker, evidence, verification]
---
# ADR 0002: CPU dependency baseline and visible recovery limits

## Context

Target GPU/VRAM are unknown; Docker is not installed locally. MediaPipe 0.10.31 Windows wheel works but its internal platform tag is incorrect.

## Options

Require CUDA, use overlapping OpenCV distributions, or use one tested CPU package closure and optional matching CUDA replacement. Persist raw clip buffers indefinitely or expose interrupted evidence failure.

## Decision

Use torch 2.7.1/torchvision .22.1 CPU pins, optional CUDA 12.6 replacements, MediaPipe Tasks .10.31 and one OpenCV distribution. Verify standard pip check and real imports rather than accepting uv metadata-only platform warnings as runtime failure. Store bounded raw windows in memory; mark pending evidence failed after worker restart. A recovered video job resumes at its cursor with a fresh temporal window.

## Consequences and deviation

GPU throughput and Compose runtime remain unverified. Full temporal/evidence continuity across process restart is not provided by this first implementation; this is a limitation relative to complete seamless recovery. Reviewers see failed evidence rather than a silently incomplete clip.
