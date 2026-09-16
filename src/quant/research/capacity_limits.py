"""User-selected account tiers, independent of transaction-cost multipliers."""


def validate_capitals(values: list[int]) -> None:
    if (not isinstance(values, list) or not 1 <= len(values) <= 2
            or any(type(v) is not int or v not in (100000, 1000000) for v in values)
            or len(set(values)) != len(values)):
        raise ValueError('Account capital tiers must be unique: 100000 and/or 1000000 CNY, at most two')
