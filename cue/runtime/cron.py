"""Minimal five-field cron matching for recurring agent tasks."""

from datetime import datetime, timedelta

_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


def _values(field: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, raw_step = part.split("/", 1)
            step = int(raw_step)
            if step <= 0:
                raise ValueError("Cron step must be positive")
        if part == "*":
            start, end = low, high
        elif "-" in part:
            start, end = (int(value) for value in part.split("-", 1))
        else:
            start = end = int(part)
        if start < low or end > high or start > end:
            raise ValueError(f"Cron value {part!r} is out of range")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError(f"Cron field {field!r} is empty")
    return values


def parse(expression: str) -> tuple[set[int], ...]:
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("Cron expression needs five fields")
    return tuple(_values(field, low, high) for field, (low, high) in zip(fields, _RANGES))


def matches(expression: str | tuple, moment: datetime) -> bool:
    minutes, hours, days, months, weekdays = parse(expression) if isinstance(expression, str) else expression
    return (moment.minute in minutes and moment.hour in hours and moment.day in days
            and moment.month in months and (moment.weekday() + 1) % 7 in weekdays)


def next_after(expression: str, after: datetime) -> datetime:
    parsed = parse(expression)
    moment = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        if matches(parsed, moment):
            return moment
        moment += timedelta(minutes=1)
    raise ValueError(f"Cron expression {expression!r} has no run within a year")
