DIGIT_CHARACTERS = frozenset("0123456789")
AREA_START = frozenset("23456789")
COUNTRY_CODE = "1"
NATIONAL_LENGTH = 10


def normalise(text: str) -> str:
    return _trimmer(_collect(text))


def _collect(text: str) -> str:
    return "".join(_kept(text))


def _kept(text: str) -> list[str]:
    kept = []
    for char in text:
        if _is_digit(char):
            kept.append(char)
    return kept


def _is_digit(char: str) -> bool:
    return char in DIGIT_CHARACTERS


def _trimmer(digits: str) -> str:
    if _has_country_code(digits):
        return _drop_first(digits)
    return digits


def _has_country_code(digits: str) -> bool:
    return _country_digits(digits) and _area_prefix(digits)


def _country_digits(digits: str) -> bool:
    return len(digits) == NATIONAL_LENGTH + 1 and digits.startswith(COUNTRY_CODE)


def _area_prefix(digits: str) -> bool:
    return digits[1] in AREA_START


def _drop_first(digits: str) -> str:
    return digits[1:]
