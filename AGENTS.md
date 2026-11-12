# SafeSight contributor instructions

Read `ai-context/INDEX.md` first. Treat this directory as the project root.
Read `docs/PLAN.md` and the relevant component nodes before changing behavior.
Update context nodes and regenerate `ai-context/graph.json` in the same change as code.
Record deviations from the approved plan in a numbered ADR and explain them to the user.
Use only synthetic fixtures for automated checks; generated fixture scripts write under
`tests/fixtures/`. Preserve existing user dataset contents. Public-source preparation may
add new files only when explicitly requested; never overwrite existing data or invent labels.
Never claim synthetic evaluation establishes production quality. Never fabricate metrics.
Keep training entrypoints independent; training shared code belongs in `training/common/`.
Runtime model loading must use the configured model directory and model cards.
Run relevant tests and `python tools/build_context_graph.py --check` before handoff.
