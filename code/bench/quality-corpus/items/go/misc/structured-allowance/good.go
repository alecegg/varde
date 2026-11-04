package corpus

// remaining returns the amount left after expenses.
func remaining(start int, expenses []int) int {
	return start - spentTotal(expenses)
}

func spentTotal(expenses []int) int {
	total := 0
	for _, expense := range expenses {
		total += expense
	}
	return total
}
