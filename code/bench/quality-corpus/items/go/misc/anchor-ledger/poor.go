package corpus

// balance returns the account balance after applying signed ledger entries.
func balance(opening int, entries []int) int {
	b := opening
	i := 0
	for i < len(entries) {
		e := entries[i]
		if e < 0 {
			if e == -3 {
				b = b - 3
			} else {
				b = b + e
			}
		} else {
			b = b + e
		}
		i = i + 1
	}
	return b
}
