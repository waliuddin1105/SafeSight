"""Worker routing checks that do not load models or access a database."""

from safesight.worker.__main__ import needs_pose_context


def test_fire_smoke_only_does_not_request_pose_context():
    assert not needs_pose_context(["fire_smoke"], {"fire_smoke": object()})


def test_pose_dependent_selected_models_request_context_when_available():
    for slug in ("body_state", "phone_usage", "cigarette_smoking", "entrance_guard"):
        assert needs_pose_context([slug], {slug: object()})


def test_missing_or_unselected_pose_model_does_not_request_context():
    assert not needs_pose_context(["cigarette_smoking"], {"fire_smoke": object()})
    assert not needs_pose_context(["fire_smoke"], {"fire_smoke": object(), "cigarette_smoking": object()})
