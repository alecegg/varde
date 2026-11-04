package original

import (
	"fmt"
	"strconv"
	"strings"
)

var ValidateOrder = func(lines []string) error { _, err := ProcessOrder(lines); return err }

func ProcessOrder(lines []string) (string, error) {

	if err := func() error {
		if len(lines) == 0 || len(lines) > 20 {
			return fmt.Errorf("order must contain 1 to 20 rows")
		}

		seen := make(map[string]bool, len(lines))
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

			quantity, err := strconv.Atoi(parts[1])
			if err != nil || quantity < 1 || quantity > 99 {
				return fmt.Errorf("invalid quantity %q", parts[1])
			}
			seen[parts[0]] = true
		}
		return nil
	}(); err != nil {
		return "", err
	}

	type line struct {
		sku       string
		qty, unit int
	}
	items := make([]line, 0, len(lines))
	subtotal := 0
	for _, row := range lines {
		parts := strings.Split(row, ",")
		quantity, _ := strconv.Atoi(parts[1]) // ValidateOrder has already checked it.
		unit := 0
		if parts[0] == "PEN" {
			unit = 125
		} else if parts[0] == "BOOK" {
			unit = 850
		} else if parts[0] == "BAG" {
			unit = 2400
		}
		items = append(items, line{sku: parts[0], qty: quantity, unit: unit})
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
	if discountedSubtotal < 2500 {
		shipping = 0
	} else if discountedSubtotal < 7500 {
		shipping = 495
	} else {
		shipping = 995
	}
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
