import re

CONTAINER_NUMBER_PATTERN = re.compile(r"^[A-Z]{4}\d{7}$")
# Código da norma ISO usada na identificação dos contêineres. É sempre definido pelo servidor.
ISO_STANDARD_CODE = "6346"


def _letter_values() -> dict[str, int]:
    # A=10, B=12, C=13... : os múltiplos de 11 (11, 22, 33) são pulados pela norma ISO 6346.
    values: dict[str, int] = {}
    value = 10
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if value % 11 == 0:
            value += 1
        values[letter] = value
        value += 1
    return values


LETTER_VALUES = _letter_values()


def normalize_container_number(raw: str) -> str:
    return raw.replace(" ", "").replace("-", "").upper()


def has_container_number_format(number: str) -> bool:
    return CONTAINER_NUMBER_PATTERN.fullmatch(number) is not None


def container_check_digit(prefix: str) -> int:
    """Dígito verificador ISO 6346 dos 10 primeiros caracteres (4 letras + 6 dígitos)."""
    total = 0
    for position, char in enumerate(prefix[:10]):
        value = LETTER_VALUES[char] if char.isalpha() else int(char)
        total += value * 2**position
    return total % 11 % 10


def has_valid_check_digit(number: str) -> bool:
    return container_check_digit(number) == int(number[10])