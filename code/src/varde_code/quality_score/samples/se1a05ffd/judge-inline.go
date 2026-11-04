package original

import (
	"fmt"
	"strconv"
	"strings"
)

func ValidateOrder(lines []string) error {
	if len(lines) == 0 || len(lines) > 20 {
		return fmt.Errorf("order must contain 1 to 20 rows")
	}
	seen := map[string]bool{}
	for _, row := range lines {
		parts := strings.Split(row, ",")
		if len(parts) != 2 {
			return fmt.Errorf("invalid row %q", row)
		}
		if parts[0] != "PEN" && parts[0] != "BOOK" && parts[0] != "BAG" {
			return fmt.Errorf("unknown sku %q", parts[0])
		}
		if seen[parts[0]] {
			return fmt.Errorf("duplicate sku %q", parts[0])
		}
		seen[parts[0]] = true
		quantity, err := strconv.Atoi(parts[1])
		if err != nil || quantity < 1 || quantity > 99 {
			return fmt.Errorf("invalid quantity %q", parts[1])
		}
	}
	return nil
}

func ProcessOrder(lines []string) (string, error) {
	if err := ValidateOrder(lines); err != nil {
		return "", err
	}
	items := make([]struct {
		sku      string
		quantity int
		unit     int
	}, 0, len(lines))
	subtotal := 0
	for _, row := range lines {
		parts := strings.Split(row, ",")
		unit := 0
		if parts[0] == "PEN" {
			unit = 125
		} else if parts[0] == "BOOK" {
			unit = 850
		} else {
			unit = 2400
		}
		quantity, _ := strconv.Atoi(parts[1])
		items = append(items, struct {
			sku      string
			quantity int
			unit     int
		}{parts[0], quantity, unit})
		subtotal += unit * quantity
	}
	discount := 0
	if subtotal >= 7500 {
		discount = (subtotal*10 + 50) / 100
	} else if subtotal >= 2500 {
		discount = (subtotal*5 + 50) / 100
	}
	discountedSubtotal := subtotal - discount
	tax := (discountedSubtotal*8 + 50) / 100
	shipping := 0
	if discountedSubtotal >= 7500 {
		shipping = 995
	} else if discountedSubtotal >= 2500 {
		shipping = 495
	}
	total := discountedSubtotal + tax + shipping
	var report strings.Builder
	for _, item := range items {
		amount := item.unit * item.quantity
		fmt.Fprintf(&report, "%s x %d: $%d.%02d\n", item.sku, item.quantity, amount/100, amount%100)
	}
	fmt.Fprintf(&report, "Subtotal: $%d.%02d\n", subtotal/100, subtotal%100)
	fmt.Fprintf(&report, "Discount: $%d.%02d\n", discount/100, discount%100)
	fmt.Fprintf(&report, "Tax: $%d.%02d\n", tax/100, tax%100)
	fmt.Fprintf(&report, "Shipping: $%d.%02d\n", shipping/100, shipping%100)
	fmt.Fprintf(&report, "Total: $%d.%02d", total/100, total%100)
	return report.String(), nil
}
