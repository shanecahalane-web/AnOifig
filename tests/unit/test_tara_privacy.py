"""Complete-message contact minimisation and numeric false-positive controls."""

import pytest

from anoifig.tara.privacy import minimise


@pytest.mark.parametrize(
    "phone",
    [
        "01 555 0123",
        "021 555 0123",
        "061 555 123",
        "00353 87 555 0123",
        "+353 87 555 0123",
        "+353 (1) 555-0123",
        "(01) 555 0123",
        "0875550123",
        "091-555-123",
        "0404 55555",
        "00353 (21) 555 0123",
        "+44 20 7946 0123",
    ],
)
def test_phone_contact_is_removed_from_complete_message(phone: str) -> None:
    result = minimise(f"Invoice Áine €1,500 for plumbing; call {phone} tomorrow.")
    assert phone not in result
    assert "€1,500" in result
    assert "Invoice Áine" in result
    assert "[contact details omitted]" in result


@pytest.mark.parametrize(
    "message",
    [
        "Charge €500.25, quantity 3, VAT 23%.",
        "The job is on 01-05-2026 and reference 20260501.",
        "Invoice 021555012 for €1,500.",
        "Use reference 1234567890 and item 5000123.",
        "Total EUR 015550123, before VAT.",
        "Total €0215550123.50.",
        "Total 061555123 EUR.",
        "Quantity 61, price 555.12, total 123.",
        "Short extension 01555 or 061555.",
    ],
)
def test_ordinary_numeric_data_is_preserved(message: str) -> None:
    assert minimise(message) == message


def test_all_known_contacts_in_one_message_are_minimised() -> None:
    message = (
        "Call 01 555 0123 or 021 555 0123; email example@example.invalid; "
        "IBAN IE29 AIBK 9311 5212 3456 78. Charge €500."
    )
    result = minimise(message)
    assert result.count("[contact details omitted]") == 4
    assert "€500" in result
    assert "example@example.invalid" not in result
    assert "IE29" not in result


def test_known_free_form_contact_is_removed_without_claiming_universal_redaction() -> None:
    assert minimise("Deliver to private marker", contact_details="private marker") == (
        "Deliver to [contact details omitted]"
    )
    # Pattern minimisation does not recognise arbitrary personal information.
    assert minimise("Customer health detail PRIVATE-MARKER") == (
        "Customer health detail PRIVATE-MARKER"
    )
