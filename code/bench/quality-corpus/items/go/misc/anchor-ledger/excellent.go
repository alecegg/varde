package corpus

// balance returns the account balance after applying signed ledger entries.
func balance(opening int, entries []int) int {
	return opening + entriesTotal(entries)
}

func entriesTotal(entries []int) int {
	total := 0
	for _, entry := range entries {
		total += entry
	}
	return total
}
