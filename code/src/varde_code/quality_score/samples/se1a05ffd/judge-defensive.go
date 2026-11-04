package original

import (
	"fmt"
	"strconv"
	"strings"
)

// orderLine stores the validated pricing data for one order row.
type orderLine struct {
	sku  string
	qty  int
	unit int
}

// ValidateOrder checks that every row has a supported SKU and quantity.
func ValidateOrder(lines []string) error {
	// Reject missing and oversized order slices before inspecting their contents.
	if lines == nil || len(lines) < 1 || len(lines) > 20 {
		return fmt.Errorf("order must contain 1 to 20 rows")
	}

	// Track SKUs so an order cannot contain the same product twice.
	seen := make(map[string]bool, len(lines))
	for _, row := range lines {
		// Split each row and reject values that do not have exactly two fields.
		parts := strings.Split(row, ",")
		if len(parts) != 2 {
			return fmt.Errorf("invalid row %q", row)
		}

		// Verify the SKU before using it as an order item.
		if !known(parts[0]) {
			return fmt.Errorf("unknown sku %q", parts[0])
		}

		// Reject repeated SKUs before recording the current row.
		if seen[parts[0]] {
			return fmt.Errorf("duplicate sku %q", parts[0])
		}
		seen[parts[0]] = true

		// Parse and bound the quantity to the accepted decimal integer range.
		n, err := strconv.Atoi(parts[1])
		if err != nil || n < 1 || n > 99 {
			return fmt.Errorf("invalid quantity %q", parts[1])
		}
	}

	// Return nil only after every row has passed validation.
	return nil
}

// ProcessOrder validates rows, calculates prices, and formats a report.
func ProcessOrder(lines []string) (string, error) {
	// Validate the complete order before performing any pricing work.
	if err := ValidateOrder(lines); err != nil {
		return "", err
	}

	// Build priced items in input order and accumulate the merchandise subtotal.
	items := make([]orderLine, 0, len(lines))
	subtotal := 0
	for _, row := range lines {
		// Split validated input so the SKU and quantity can be priced separately.
		parts := strings.Split(row, ",")
		if len(parts) != 2 {
			return "", fmt.Errorf("invalid row %q", row)
		}

		// Select the fixed unit price for the validated SKU.
		unit := 0
		switch parts[0] {
		case "PEN":
			unit = 125
		case "BOOK":
			unit = 850
		case "BAG":
			unit = 2400
		default:
			return "", fmt.Errorf("unknown sku %q", parts[0])
		}

		// Parse the validated quantity and retain a guard for defensive safety.
		quantity, err := strconv.Atoi(parts[1])
		if err != nil || quantity < 1 || quantity > 99 {
			return "", fmt.Errorf("invalid quantity %q", parts[1])
		}

		// Preserve the row for the report and add its extended price.
		items = append(items, orderLine{sku: parts[0], qty: quantity, unit: unit})
		subtotal += unit * quantity
	}

	// Guard against an unexpectedly empty item list before calculating totals.
	if len(items) == 0 {
		return "", fmt.Errorf("empty order")
	}

	// Apply the applicable percentage discount using cent-rounded arithmetic.
	discount := 0
	if subtotal >= 7500 {
		discount = (subtotal*10 + 50) / 100
	} else if subtotal >= 2500 {
		discount = (subtotal*5 + 50) / 100
	}

	// Calculate tax on the discounted merchandise amount.
	base := subtotal - discount
	tax := (base*8 + 50) / 100

	// Choose shipping based on the discounted merchandise amount.
	shipping := 0
	if base >= 7500 {
		shipping = 995
	} else if base >= 2500 {
		shipping = 495
	}

	// Combine discounted merchandise, tax, and shipping into the order total.
	total := base + tax + shipping

	// Format each line item first, preserving the original input order.
	var report strings.Builder
	for _, item := range items {
		fmt.Fprintf(&report, "%s x %d: $%d.%02d\n", item.sku, item.qty, item.unit*item.qty/100, item.unit*item.qty%100)
	}

	// Append the financial summary with each value expressed in dollars and cents.
	fmt.Fprintf(&report, "Subtotal: $%d.%02d\n", subtotal/100, subtotal%100)
	fmt.Fprintf(&report, "Discount: $%d.%02d\n", discount/100, discount%100)
	fmt.Fprintf(&report, "Tax: $%d.%02d\n", tax/100, tax%100)
	fmt.Fprintf(&report, "Shipping: $%d.%02d\n", shipping/100, shipping%100)
	fmt.Fprintf(&report, "Total: $%d.%02d", total/100, total%100)

	// Return the completed report after all calculations succeed.
	return report.String(), nil
}

// known reports whether a SKU belongs to the supported catalog.
func known(s string) bool {
	// Match only the three SKU codes defined by the order rules.
	return s == "PEN" || s == "BOOK" || s == "BAG"
}
