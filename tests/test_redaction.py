from copilot.redaction import redact_text


def test_redacts_email_and_long_numbers() -> None:
    assert redact_text("Contact person@example.com about account 123456789.") == (
        "Contact [REDACTED_EMAIL] about account [REDACTED_NUMBER]."
    )
