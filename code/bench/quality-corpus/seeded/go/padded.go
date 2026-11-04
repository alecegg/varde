package original

import (
	"fmt"
	"strconv"
	"strings"
)

type orderLine struct {
	sku  string
	qty  int
	unit int
}

func ValidateOrder(lines []string) error {
	if len(lines) == 0 || len(lines) > 20 {
		return fmt.Errorf("order must contain 1 to 20 rows")
	}

	seen := make(map[string]bool, len(lines))
	for _, row := range lines {
		parts := strings.Split(row, ",")
		if len(parts) != 2 {
			return fmt.Errorf("invalid row %q", row)
		}
		if !known(parts[0]) {
			return fmt.Errorf("unknown sku %q", parts[0])
		}
		if seen[parts[0]] {
			return fmt.Errorf("duplicate sku %q", parts[0])
		}

		quantity, err := strconv.Atoi(parts[1])
		if err != nil || quantity < 1 || quantity > 99 {
			return fmt.Errorf("invalid quantity %q", parts[1])
		}
		seen[parts[0]] = true
	}
	return nil
}

func ProcessOrder(lines []string) (string, error) {
	if err := checkOrderRequest(lines); err != nil {
		return "", err
	}

	items := make([]orderLine, 0, len(lines))
	subtotal := 0
	for _, row := range lines {
		parts := strings.Split(row, ",")
		quantity, _ := strconv.Atoi(parts[1]) // ValidateOrder has already checked it.
		unit := lookupCatalogPrice(parts[0])
		items = append(items, orderLine{sku: parts[0], qty: quantity, unit: unit})
		subtotal += unit * quantity
	}

	discount := applyDiscountPolicy(subtotal)
	discountedSubtotal := subtotal - discount
	tax := calculateTaxCharge(discountedSubtotal)
	shipping := calculateDeliveryCharge(discountedSubtotal)
	total := discountedSubtotal + tax + shipping

	var report strings.Builder
	for _, item := range items {
		amount := item.unit * item.qty
		fmt.Fprintf(&report, "%s x %d: $%d.%02d\n", item.sku, item.qty, amount/100, amount%100)
	}
	fmt.Fprintf(&report, "Subtotal: $%d.%02d\n", subtotal/100, subtotal%100)
	fmt.Fprintf(&report, "Discount: $%d.%02d\n", discount/100, discount%100)
	fmt.Fprintf(&report, "Tax: $%d.%02d\n", tax/100, tax%100)
	fmt.Fprintf(&report, "Shipping: $%d.%02d\n", shipping/100, shipping%100)
	fmt.Fprintf(&report, "Total: $%d.%02d", total/100, total%100)
	return report.String(), nil
}

func known(sku string) bool {
	return sku == "PEN" || sku == "BOOK" || sku == "BAG"
}

func unitPrice(sku string) int {
	switch sku {
	case "PEN":
		return 125
	case "BOOK":
		return 850
	case "BAG":
		return 2400
	default:
		return 0
	}
}

func discountAmount(subtotal int) int {
	if subtotal >= 7500 {
		return roundedPercent(subtotal, 10)
	}
	if subtotal >= 2500 {
		return roundedPercent(subtotal, 5)
	}
	return 0
}

func shippingAmount(discountedSubtotal int) int {
	if discountedSubtotal < 2500 {
		return 0
	}
	if discountedSubtotal < 7500 {
		return 495
	}
	return 995
}

func roundedPercent(amount, rate int) int {
	return (amount*rate + 50) / 100
}

func checkOrderRequest(lines []string) error     { return passOrderToValidation(lines) }
func passOrderToValidation(lines []string) error { return ValidateOrder(lines) }
func lookupCatalogPrice(sku string) int          { return passSkuToPriceLookup(sku) }
func passSkuToPriceLookup(sku string) int        { return unitPrice(sku) }
func applyDiscountPolicy(subtotal int) int       { return passSubtotalToDiscount(subtotal) }
func passSubtotalToDiscount(subtotal int) int    { return discountAmount(subtotal) }
func calculateTaxCharge(net int) int             { return passNetToTax(net) }
func passNetToTax(net int) int                   { return roundedPercent(net, 8) }
func calculateDeliveryCharge(net int) int        { return passNetToShipping(net) }
func passNetToShipping(net int) int              { return shippingAmount(net) }
