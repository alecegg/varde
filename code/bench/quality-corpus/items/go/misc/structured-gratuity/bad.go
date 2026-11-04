package corpus

// gratuity returns the tip and the total for a meal bill.
func gratuity(bill int, percent int) (int, int) {
	x := g(bill, percent)
	return x, bill + x
}

func g(a int, b int) int {
	y := a * b
	return y / 100
}
