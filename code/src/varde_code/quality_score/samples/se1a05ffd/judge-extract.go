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
	if err := validateCount(lines); err != nil { return err }
	return validateRows(lines)
}

func validateCount(lines []string) error {
	if len(lines) == 0 || len(lines) > 20 { return fmt.Errorf("order must contain 1 to 20 rows") }
	return nil
}

func validateRows(lines []string) error {
	seen := map[string]bool{}
	for _, row := range lines { if err := validateRow(row, seen); err != nil { return err } }
	return nil
}

func validateRow(row string, seen map[string]bool) error {
	parts := strings.Split(row, ",")
	if len(parts) != 2 { return fmt.Errorf("invalid row %q", row) }
	return validateParts(parts, seen)
}

func validateParts(parts []string, seen map[string]bool) error {
	if !known(parts[0]) { return fmt.Errorf("unknown sku %q", parts[0]) }
	if seen[parts[0]] { return fmt.Errorf("duplicate sku %q", parts[0]) }
	return markAndValidateQuantity(parts, seen)
}

func markAndValidateQuantity(parts []string, seen map[string]bool) error {
	seen[parts[0]] = true
	qty, err := strconv.Atoi(parts[1])
	if err != nil || qty < 1 || qty > 99 { return fmt.Errorf("invalid quantity %q", parts[1]) }
	return nil
}

func ProcessOrder(lines []string) (string, error) {
	if err := ValidateOrder(lines); err != nil { return "", err }
	items := parseLines(lines)
	return renderOrder(items), nil
}

func parseLines(lines []string) []orderLine {
	items := make([]orderLine, 0, len(lines))
	for _, row := range lines { items = append(items, parseLine(row)) }
	return items
}

func parseLine(row string) orderLine {
	parts := strings.Split(row, ",")
	qty, _ := strconv.Atoi(parts[1])
	return orderLine{sku: parts[0], qty: qty, unit: unitPrice(parts[0])}
}

func unitPrice(sku string) int {
	switch sku { case "PEN": return 125; case "BOOK": return 850; case "BAG": return 2400 }
	return 0
}

func renderOrder(items []orderLine) string {
	subtotal := subtotalOf(items)
	discount := discountOf(subtotal)
	base := subtotal - discount
	return report(items, subtotal, discount, taxOf(base), shippingOf(base), base)
}

func subtotalOf(items []orderLine) int {
	total := 0
	for _, item := range items { total += item.unit * item.qty }
	return total
}

func discountOf(subtotal int) int {
	if subtotal >= 7500 { return roundedPercent(subtotal, 10) }
	if subtotal >= 2500 { return roundedPercent(subtotal, 5) }
	return 0
}

func roundedPercent(amount, rate int) int { return (amount*rate + 50) / 100 }

func taxOf(base int) int { return roundedPercent(base, 8) }

func shippingOf(base int) int {
	if base < 2500 { return 0 }
	if base < 7500 { return 495 }
	return 995
}

func report(items []orderLine, subtotal, discount, tax, shipping, base int) string {
	var out strings.Builder
	writeItems(&out, items)
	writeSummary(&out, subtotal, discount, tax, shipping, base+tax+shipping)
	return out.String()
}

func writeItems(out *strings.Builder, items []orderLine) {
	for _, item := range items { writeItem(out, item) }
}

func writeItem(out *strings.Builder, item orderLine) {
	amount := item.unit * item.qty
	fmt.Fprintf(out, "%s x %d: $%d.%02d\n", item.sku, item.qty, amount/100, amount%100)
}

func writeSummary(out *strings.Builder, subtotal, discount, tax, shipping, total int) {
	writeMoneyLine(out, "Subtotal: $", subtotal)
	writeMoneyLine(out, "Discount: $", discount)
	writeMoneyLine(out, "Tax: $", tax)
	writeMoneyLine(out, "Shipping: $", shipping)
	writeMoney(out, "Total: $", total)
}

func writeMoneyLine(out *strings.Builder, format string, amount int, values ...any) {
	fmt.Fprintf(out, format+"%d.%02d\n", append(values, amount/100, amount%100)...)
}

func writeMoney(out *strings.Builder, label string, amount int) {
	fmt.Fprintf(out, "%s%d.%02d", label, amount/100, amount%100)
}

func known(s string) bool { return s == "PEN" || s == "BOOK" || s == "BAG" }
