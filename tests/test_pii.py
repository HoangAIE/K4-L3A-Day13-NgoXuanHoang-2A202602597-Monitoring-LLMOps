from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_cccd() -> None:
    cccd_samples = (
        "001099123456",
        "001 099 123 456",
        "001-099-123-456",
    )
    for cccd in cccd_samples:
        out = scrub_text(f"CCCD của tôi là {cccd}")
        assert cccd not in out
        assert "REDACTED_CCCD" in out


def test_scrub_credit_card() -> None:
    card_samples = (
        "4111222233334444",
        "4111 2222 3333 4444",
        "4111-2222-3333-4444",
    )
    for card in card_samples:
        out = scrub_text(f"Card number: {card}")
        assert card not in out
        assert "REDACTED_CREDIT_CARD" in out

