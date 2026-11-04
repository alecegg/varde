from varde_code.quality_score.fixedpoint import MICRO, from_decimal, to_decimal


def test_decimal_strings_have_stable_micro_values() -> None:
    values = [from_decimal("1.234567"), from_decimal("0.000001"), from_decimal("-2.5")]

    assert values == [1_234_567, 1, -2_500_000]
    assert [from_decimal(value) for value in ("1.234567", "0.000001", "-2.5")] == values
    assert to_decimal(1_234_567, 2) == "1.23"
    assert MICRO == 1_000_000


def test_decimal_strings_reject_implicit_rounding() -> None:
    try:
        from_decimal("0.0000001")
    except ValueError:
        pass
    else:
        raise AssertionError("excess precision must not be silently rounded")
