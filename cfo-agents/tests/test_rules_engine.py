from app.services.rules_engine import (
    normalize_merchant,
    suggest_account_code,
)


def test_normalize_merchant_aws_variants():
    assert normalize_merchant("AWS USA") == "Amazon Web Services"
    assert normalize_merchant("amazon web services") == "Amazon Web Services"
    assert normalize_merchant("amzn  retail") == "Amazon"


def test_normalize_merchant_passthrough():
    assert normalize_merchant("Random Vendor 2026-05-01") == "Random Vendor"


def test_suggest_account_code_hosting():
    assert suggest_account_code("AWS")[0] == "420"
    assert suggest_account_code("Slack subscription")[0] == "420"


def test_suggest_account_code_travel():
    assert suggest_account_code("Uber trip")[0] == "493"
    assert suggest_account_code("Airbnb stay")[0] == "493"


def test_suggest_account_code_no_match():
    assert suggest_account_code("Mystery merchant 12345") is None
