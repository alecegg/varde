import solution

assert solution.total_minutes("1h30m") == 90
assert solution.total_minutes("45m") == 45
assert solution.total_minutes("2h") == 120
assert solution.total_minutes("0m") == 0
assert solution.total_minutes("") == 0
assert solution.total_minutes("1m") == 1
assert solution.total_minutes("10h5m") == 605
assert solution.total_minutes("3h0m") == 180
assert solution.total_minutes("99m") == 99

try:
    solution.total_minutes("abc")
except ValueError:
    pass
else:
    raise AssertionError("abc must be rejected")
