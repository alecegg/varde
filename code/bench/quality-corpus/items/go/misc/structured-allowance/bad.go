package corpus

// remaining returns the amount left after expenses.
func remaining(start int, expenses []int) int {
	if len(expenses) > 1 {
		amount := start
		index := 0
		for index < len(expenses) {
			amount = amount - expenses[index]
			index = index + 1
		}
		return amount
	}
	amount := start
	for _, expense := range expenses {
		amount = amount - expense
	}
	return amount
}
