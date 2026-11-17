"""A preview must disclose the complete exact change and fit one message."""

import pytest

from anoifig.tara.service import proposal_preview


def test_preview_is_deterministic_and_includes_removals_and_line_changes():
    before = {"amount": "600", "line_items": [{"description": "tap", "quantity": "1"}]}
    after = {"amount": None, "line_items": [{"description": "tap", "quantity": "2"}]}
    token = "A" * 32
    preview = proposal_preview(before, after, token)
    assert 'amount: "600" → null' in preview
    assert '"quantity": "1"' in preview
    assert '"quantity": "2"' in preview
    assert f"APPLY {token}" in preview
    assert f"REJECT {token}" in preview
    assert preview == proposal_preview(dict(reversed(list(before.items()))), after, token)


def test_oversized_preview_fails_instead_of_truncating():
    with pytest.raises(ValueError, match="too long"):
        proposal_preview({"work": "x" * 900}, {"work": "y" * 900}, "A" * 32)


def test_preview_preserves_irish_names_and_escapes_invisible_formatting():
    preview = proposal_preview({"name": "Áine"}, {"name": "Seán\u202e"}, "A" * 32)
    assert "Áine" in preview
    assert "Seán\\u202e" in preview
    assert "\u202e" not in preview
