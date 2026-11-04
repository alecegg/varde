import solution
assert solution.gratuity(bill=20, percent=10) == {"gratuity": 2, "total": 22}
assert solution.gratuity(bill=45, percent=20) == {"gratuity": 9, "total": 54}
assert solution.gratuity(bill=0, percent=15) == {"gratuity": 0, "total": 0}
