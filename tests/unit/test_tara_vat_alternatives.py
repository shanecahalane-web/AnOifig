"""VAT rates and treatments need one affirmative, unambiguous instruction."""

import pytest

from anoifig.tara.schemas import (
    InvoiceNotes,
    ProposedNotes,
    _vat_rate_evidence,
    apply_proposal,
    vat_evidence,
)


def change(field, value, evidence):
    return ProposedNotes.model_validate(
        {
            "intent": "correction",
            "changes": [{"field": field, "value": value, "evidence": evidence}],
            "line_items": None,
            "line_items_evidence": None,
        }
    )


TREATMENT_REPLACEMENTS = [
    "Use VAT exempt instead of VAT 23%.",
    "Use VAT 23% instead of VAT exempt.",
    "Use VAT exempt rather than VAT 23%.",
    "Use VAT 23% rather than VAT exempt.",
]


RATE_CHOICES = [
    "VAT 23%, VAT exempt",
    "VAT exempt, VAT 23%",
    "VAT 23% and zero-rated",
    "Zero-rated and VAT 23%",
    "VAT 23% and no VAT",
    "No VAT and VAT 23%",
    "VAT 23% or VAT exempt",
    "VAT 23% or exempt",
    "VAT 23% or zero-rated",
    "VAT 23% or no VAT",
    "VAT 23% versus VAT exempt",
    "VAT 23% vs zero rated",
    "VAT 23% / VAT exempt",
    "VAT 23%/zero-rated",
    "VAT 23% or VAT exemption",
    "VAT 23% or zero\u2011rated",
    "VAT 23% / 0% VAT",
    "Either VAT 23% or no VAT",
    "Choose between VAT 23% and VAT exempt",
    "VAT 23%, alternatively exempt",
    "VAT 23%, or VAT exempt",
    "VAT 23%. Or VAT exempt",
    "VAT 23%; or VAT exempt",
    "VAT 23%\nor zero-rated",
    "VAT 23% or\nVAT exempt",
    "VAT 23% or \nexempt",
    "VAT 23% alternatively; exempt",
    "VAT 23% /\nVAT exempt",
    "VAT 23% versus\nVAT exempt",
    "VAT 23% alternatively\nexempt",
    "VAT 23%; alternatively exempt",
    "VAT 23% or should it be zero-rated",
    "Choose VAT 23% and VAT exempt",
    "VAT 23% or VAT exempt?",
    "Is VAT 23% or zero-rated correct?",
    *TREATMENT_REPLACEMENTS,
]


@pytest.mark.parametrize("message", RATE_CHOICES)
def test_rate_validator_rejects_a_nonnumeric_treatment_alternative(message):
    assert not _vat_rate_evidence("23", message, message, None)


@pytest.mark.parametrize("cropped", [False, True], ids=["full", "cropped"])
@pytest.mark.parametrize("message", RATE_CHOICES)
def test_rate_proposal_cannot_drop_an_exemption_alternative(message, cropped):
    original = InvoiceNotes(vat_basis="exclusive", vat_rate="13.5", amount="500")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, change("vat_rate", "23", "23%" if cropped else message), message)
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "message",
    [
        "VAT exempt versus VAT 23%",
        "VAT exempt / 23% VAT",
        "No VAT versus zero-rated",
        "VAT exempt / zero-rated",
        "No VAT or VAT 0%",
        "VAT exempt, VAT 23%",
        "VAT exempt and zero-rated",
        "Zero-rated and no VAT",
        *TREATMENT_REPLACEMENTS,
    ],
)
def test_basis_validator_and_proposal_preserve_information_on_treatment_choices(message):
    assert not vat_evidence("no_vat", message)
    original = InvoiceNotes(vat_basis="exclusive", vat_rate="13.5", amount="500")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, change("vat_basis", "no_vat", message), message)
    assert original.model_dump() == before


@pytest.mark.parametrize("message", TREATMENT_REPLACEMENTS)
def test_basis_correction_cannot_crop_a_rejected_or_replacement_treatment(message):
    original = InvoiceNotes(vat_basis="exclusive", vat_rate="13.5", amount="500")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, change("vat_basis", "no_vat", "VAT exempt"), message)
    assert original.model_dump() == before


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("Use VAT 23%, excluding VAT.", "vat_rate", "23"),
        ("Use VAT 0%, excluding VAT.", "vat_rate", "0"),
        ("The VAT rate is 0", "vat_rate", "0"),
        ("Use VAT 23% for repairs or installation.", "vat_rate", "23"),
        ("VAT 23%. Is the repair complete?", "vat_rate", "23"),
        ("VAT 23%; choose repairs or replacement.", "vat_rate", "23"),
        ("VAT 23% for repairs or\ninstallation. The old job was exempt.", "vat_rate", "23"),
        ("VAT exempt.", "vat_basis", "no_vat"),
        ("VAT exempt. Repairs or installation are fine.", "vat_basis", "no_vat"),
        ("No VAT, not registered.", "vat_basis", "no_vat"),
    ],
)
def test_explicit_affirmative_vat_updates_remain_supported(message, field, value):
    original = InvoiceNotes(vat_basis="exclusive", vat_rate="13.5", amount="500")
    result = apply_proposal(original, change(field, value, message), message)
    assert getattr(result, field) == value
    assert result.amount == "500"
    if field == "vat_rate":
        assert result.vat_basis == "exclusive"
    else:
        assert result.vat_rate == "13.5"


@pytest.mark.parametrize(
    "message,field,value",
    [
        ("VAT exempt.", "vat_rate", "0"),
        ("No VAT.", "vat_rate", "0"),
        ("Zero-rated.", "vat_rate", "0"),
        ("Zero-rated.", "vat_basis", "no_vat"),
        ("VAT 0%.", "vat_basis", "no_vat"),
    ],
)
def test_exemption_and_zero_percent_are_not_automatically_interchangeable(message, field, value):
    original = InvoiceNotes(vat_basis="exclusive", vat_rate="13.5")
    before = original.model_dump()
    with pytest.raises(ValueError):
        apply_proposal(original, change(field, value, message), message)
    assert original.model_dump() == before
