import pytest

from fastclm.lifecycle import next_statuses, require_transition


def test_reviewed_lifecycle_allows_forward_and_revision_paths():
    require_transition("draft", "review")
    require_transition("review", "draft")
    require_transition("approval", "signature")
    require_transition("active", "terminated")
    assert next_statuses("signature") == ("active", "approval")


def test_lifecycle_rejects_skipped_and_terminal_transitions():
    with pytest.raises(ValueError):
        require_transition("draft", "active")
    with pytest.raises(ValueError):
        require_transition("terminated", "draft")
