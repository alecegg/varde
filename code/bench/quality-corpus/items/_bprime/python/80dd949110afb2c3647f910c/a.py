DIGIT_CHARACTERS = "0123456789"
AREA_START = "23456789"
NATIONAL_LENGTH = 10


def normalise(text: str) -> str:
    digits = "".join(char for char in text if char in DIGIT_CHARACTERS)
    if _has_country_code(digits):
        return digits[1:]
    return digits


def _has_country_code(digits: str) -> bool:
    return (
        len(digits) == NATIONAL_LENGTH + 1
        and digits.startswith("1")
        and digits[1] in AREA_START
    )
