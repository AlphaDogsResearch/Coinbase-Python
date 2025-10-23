from decimal import Decimal


def convert_to_decimal(value) -> Decimal:
    if type(value) == str:
        return convert_str_to_decimal(value)
    elif type(value) == float:
        return convert_float_to_decimal(value)
    else:
        return value

def is_multiple_of(x:float, base:float, tol='1e-12') -> bool:
    x = Decimal(str(x))
    base = Decimal(str(base))
    tol = Decimal(str(tol))
    remainder = x % base
    return remainder < tol or abs(remainder - base) < tol

def convert_float_to_decimal(float_value: float) -> Decimal:
    return convert_str_to_decimal(str(float_value))

def convert_str_to_decimal(str_value: str) -> Decimal:
    return Decimal(str_value)

def add_numbers(x: float, y: float) -> float:
    return float(convert_float_to_decimal(x) + convert_float_to_decimal(y))