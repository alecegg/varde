import solution

assert solution.normalise("+1 (555) 123-4567") == "5551234567"
assert solution.normalise("555-123-4567") == "5551234567"
assert solution.normalise("(020) 7946 0958") == "02079460958"
assert solution.normalise("") == ""
assert solution.normalise("1") == "1"
assert solution.normalise("15551234567") == "5551234567"
assert solution.normalise("+44 20 7946 0958") == "442079460958"
assert solution.normalise("55512345678") == "55512345678"
assert solution.normalise("   ") == ""
assert solution.normalise("1-800-FLOWERS") == "1800"
assert solution.normalise("1-055-555-0100") == "10555550100"
