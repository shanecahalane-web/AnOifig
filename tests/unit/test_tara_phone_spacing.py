"""Formatted phone contacts retain the same numeric false-positive controls."""

import pytest

from anoifig.tara.privacy import minimise


@pytest.mark.parametrize("separator", ["\u00a0", "\u202f"])
@pytest.mark.parametrize(
    "phone",
    [
        "01 555 0123",
        "021 555 0123",
        "061 555 123",
        "087 555 0123",
        "00353 87 555 0123",
        "+353 (1) 555 0123",
        "+44 20 7946 0123",
    ],
)
def test_nonbreaking_phone_groups_are_minimised(phone: str, separator: str) -> None:
    formatted_phone = phone.replace(" ", separator)
    message = f"Boiler repairs; call {formatted_phone} tomorrow. Charge €1,500.25."
    assert minimise(message) == (
        "Boiler repairs; call [contact details omitted] tomorrow. Charge €1,500.25."
    )


def test_mixed_horizontal_separators_are_minimised() -> None:
    assert minimise("Call +3\u00a05 3\t(87)\u202f555-0123 tomorrow.") == (
        "Call [contact details omitted] tomorrow."
    )


@pytest.mark.parametrize("separator", ["\u00a0", "\u202f"])
@pytest.mark.parametrize(
    "message",
    [
        "The job is on 01 05 2026 and reference 20260501.",
        "Invoice 021 555 012 for €1,500.",
        "Use reference 1234567890 and item 5000123.",
        "Total EUR 01 555 0123, before VAT.",
        "Total 061 555 123 EUR.",
        "Total €021 555 0123.50.",
        "Quantity 61, price 555.12, total 123.",
        "Short extension 01 555 or 061 555.",
        "Long reference 01 555 0123 45.",
    ],
)
def test_formatted_unrelated_numeric_information_is_preserved(message: str, separator: str) -> None:
    formatted_message = message.replace(" ", separator)
    assert minimise(formatted_message) == formatted_message
