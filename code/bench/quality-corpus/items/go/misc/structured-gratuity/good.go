package corpus

// gratuity returns the tip and the total for a meal bill.
func gratuity(bill int, percent int) (int, int) {
	amount := bill * percent / 100
	return amount, bill + amount
}
