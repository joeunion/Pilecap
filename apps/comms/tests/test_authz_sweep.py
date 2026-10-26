"""The comms keys conform to the vocabulary, and the retired words still answer.

The per-role matrix is core's (`apps/core/tests/test_flat_baseline_document.py`); role-reading
predicates are rule 54 (c)'s.
"""

from __future__ import annotations

import pytest

from apps.core.authz import renamed_permissions, vocabulary

pytestmark = pytest.mark.django_db


def comms_keys() -> list[str]:
    """Every key this app owns, derived from the vocabulary."""
    return sorted(action for action, word in vocabulary().items() if word.app == "comms")


def test_every_comms_key_conforms_and_the_renames_answer() -> None:
    """Every comms key fits the pattern, and a renamed key resolves to its successor."""
    from apps.comms import policies as comms_policies

    words = vocabulary()
    non_conforming = [action for action in comms_keys() if not words[action].conforms]
    assert non_conforming == [], non_conforming

    renames = renamed_permissions()
    for old, new in comms_policies.RENAMED_PERMISSIONS.items():
        assert renames[old] == new
        assert new in words
        assert old in words[new].renamed_from
