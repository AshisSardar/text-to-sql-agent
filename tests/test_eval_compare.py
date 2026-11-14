from datetime import date, datetime
from decimal import Decimal

from eval.run_eval import results_match


def test_same_rows_different_order_and_column_order():
    expected = [("Kolkata", 38), ("Delhi", 42)]
    actual = [(42, "Delhi"), (38, "Kolkata")]
    assert results_match(expected, actual)


def test_extra_columns_allowed():
    assert results_match([("Running Shoes",)], [(7, "Running Shoes", Decimal("2799.00"))])


def test_numbers_rounded_and_dates_normalized():
    assert results_match([(Decimal("4125.7175"),)], [(4125.72,)])
    assert results_match([(date(2026, 11, 2), 5)], [(datetime(2026, 11, 2), Decimal("5.00"))])


def test_wrong_value_or_row_count_fails():
    assert not results_match([("Delhi", 42)], [("Delhi", 41)])
    assert not results_match([("Delhi", 42)], [("Delhi", 42), ("Kolkata", 38)])
    assert not results_match([(1, 2)], [(1,)])


def test_quota_error_detected_only_for_api_errors():
    from eval.run_eval import is_quota_error

    assert is_quota_error({"status": "api_error", "error": "ResourceExhausted: 429 RESOURCE_EXHAUSTED"})
    assert not is_quota_error({"status": "api_error", "error": "TimeoutError: timed out"})
    assert not is_quota_error({"status": "done", "error": "column x does not exist"})
