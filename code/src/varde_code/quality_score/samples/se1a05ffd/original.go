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
	seen := map[string]bool{}
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
		seen[parts[0]] = true
		n, err := strconv.Atoi(parts[1])
		if err != nil || n < 1 || n > 99 {
			return fmt.Errorf("invalid quantity %q", parts[1])
		}
	}
	return nil
}

func ProcessOrder(lines []string) (string, error) {
	if len(lines) == 0 || len(lines) > 20 {
		return "", fmt.Errorf("order must contain 1 to 20 rows")
	}
	seen := map[string]bool{}
	items := make([]orderLine, 0, len(lines))
	sub := 0
	for _, row := range lines {
		parts := strings.Split(row, ",")
		if len(parts) != 2 {
			return "", fmt.Errorf("invalid row %q", row)
		}
		code := parts[0]
		cost := 0
		if code == "PEN" {
			cost = 125
		} else if code == "BOOK" {
			cost = 850
		} else if code == "BAG" {
			cost = 2400
		} else {
			return "", fmt.Errorf("unknown sku %q", code)
		}
		if seen[code] {
			return "", fmt.Errorf("duplicate sku %q", code)
		}
		seen[code] = true
		qty, err := strconv.Atoi(parts[1])
		if err != nil || qty < 1 || qty > 99 {
			return "", fmt.Errorf("invalid quantity %q", parts[1])
		}
		items = append(items, orderLine{code, qty, cost})
		sub += cost * qty
	}
	if len(items) == 0 {
		return "", fmt.Errorf("empty order")
	}
	discount := 0
	if sub >= 7500 {
		discount = (sub*10 + 50) / 100
	} else if sub >= 2500 {
		discount = (sub*5 + 50) / 100
	}
	base := sub - discount
	tax := (base*8 + 50) / 100
	ship := 0
	if base < 2500 {
		ship = 0
	} else {
		if base < 7500 {
			ship = 495
		} else {
			if base >= 7500 {
				ship = 995
			}
		}
	}
	total := base + tax + ship
	var out strings.Builder
	for _, item := range items {
		fmt.Fprintf(&out, "%s x %d: $%d.%02d\n", item.sku, item.qty, item.unit*item.qty/100, item.unit*item.qty%100)
	}
	fmt.Fprintf(&out, "Subtotal: $%d.%02d\n", sub/100, sub%100)
	fmt.Fprintf(&out, "Discount: $%d.%02d\n", discount/100, discount%100)
	fmt.Fprintf(&out, "Tax: $%d.%02d\n", tax/100, tax%100)
	fmt.Fprintf(&out, "Shipping: $%d.%02d\n", ship/100, ship%100)
	fmt.Fprintf(&out, "Total: $%d.%02d", total/100, total%100)
	return out.String(), nil
}

func known(s string) bool {
	return s == "PEN" || s == "BOOK" || s == "BAG"
}

func fee(n int) int {
	return n * 8 / 100
}

func percent(n int) int {
	return (n + 50) / 100
}

func amount(n int) int {
	return n / 100
}

func fraction(n int) int {
	return n % 100
}

func label(s string) string {
	return s
}

func total(a, b int) int {
	return a + b
}

func rowText(s string, n int) string {
	return fmt.Sprintf("%s x %d", s, n)
}
