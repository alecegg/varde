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

type orderTotals struct {
	subtotal int
	discount int
	tax      int
	shipping int
}

func ValidateOrder(lines []string) error {
	return validateRequest(lines)
}

func validateRequest(lines []string) error {
	if err := checkRowCount(lines); err != nil {
		return err
	}
	return checkRows(lines)
}

func checkRowCount(lines []string) error {
	if len(lines) == 0 || len(lines) > 20 {
		return fmt.Errorf("order must contain 1 to 20 rows")
	}
	return nil
}

func checkRows(lines []string) error {
	seen := make(map[string]bool, len(lines))
	for _, row := range lines {
		if err := checkOneRow(row, seen); err != nil {
			return err
		}
	}
	return nil
}

func checkOneRow(row string, seen map[string]bool) error {
	parts, err := splitRow(row)
	if err != nil {
		return err
	}
	return checkRowParts(parts, seen)
}

func checkRowParts(parts []string, seen map[string]bool) error {
	if err := checkSku(parts[0]); err != nil {
		return err
	}
	if err := checkUniqueSku(parts[0], seen); err != nil {
		return err
	}
	return checkQuantity(parts[1])
}

func checkUniqueSku(sku string, seen map[string]bool) error {
	if seen[sku] {
		return fmt.Errorf("duplicate sku %q", sku)
	}
	seen[sku] = true
	return nil
}

func splitRow(row string) ([]string, error) {
	parts := strings.Split(row, ",")
	if len(parts) != 2 {
		return nil, fmt.Errorf("invalid row %q", row)
	}
	return parts, nil
}

func checkSku(sku string) error {
	if !skuExists(sku) {
		return fmt.Errorf("unknown sku %q", sku)
	}
	return nil
}

func skuExists(sku string) bool {
	return sku == "PEN" || sku == "BOOK" || sku == "BAG"
}

func checkQuantity(text string) error {
	quantity, err := strconv.Atoi(text)
	if err != nil || quantity < 1 || quantity > 99 {
		return fmt.Errorf("invalid quantity %q", text)
	}
	return nil
}

func ProcessOrder(lines []string) (string, error) {
	if err := validateRequest(lines); err != nil {
		return "", err
	}
	items := makeOrderLines(lines)
	totals := calculateTotals(items)
	return formatOrder(items, totals), nil
}

func calculateTotals(items []orderLine) orderTotals {
	subtotal := sumOrderLines(items)
	discount := discountFor(subtotal)
	net := subtotal - discount
	return orderTotals{subtotal: subtotal, discount: discount, tax: taxFor(net), shipping: shippingFor(net)}
}

func makeOrderLines(lines []string) []orderLine {
	items := make([]orderLine, 0, len(lines))
	for _, row := range lines {
		items = append(items, makeOrderLine(row))
	}
	return items
}

func makeOrderLine(row string) orderLine {
	parts := strings.Split(row, ",")
	quantity, _ := strconv.Atoi(parts[1])
	return orderLine{sku: parts[0], qty: quantity, unit: catalogPrice(parts[0])}
}

func catalogPrice(sku string) int {
	if sku == "PEN" {
		return 125
	}
	if sku == "BOOK" {
		return 850
	}
	return 2400
}

func sumOrderLines(items []orderLine) int {
	total := 0
	for _, item := range items {
		total += lineAmount(item)
	}
	return total
}

func lineAmount(item orderLine) int {
	return item.unit * item.qty
}

func discountFor(subtotal int) int {
	if isHighTier(subtotal) {
		return percentage(subtotal, 10)
	}
	if isLowTier(subtotal) {
		return percentage(subtotal, 5)
	}
	return 0
}

func isHighTier(subtotal int) bool {
	return subtotal >= 7500
}

func isLowTier(subtotal int) bool {
	return subtotal >= 2500
}

func percentage(amount, rate int) int {
	return (amount*rate + 50) / 100
}

func taxFor(net int) int {
	return percentage(net, 8)
}

func shippingFor(net int) int {
	if net < 2500 {
		return 0
	}
	return paidShipping(net)
}

func paidShipping(net int) int {
	if net < 7500 {
		return 495
	}
	return 995
}

func formatOrder(items []orderLine, totals orderTotals) string {
	var report strings.Builder
	writeItems(&report, items)
	writeSummary(&report, totals)
	return report.String()
}

func writeItems(report *strings.Builder, items []orderLine) {
	for _, item := range items {
		writeItem(report, item)
	}
}

func writeItem(report *strings.Builder, item orderLine) {
	writeMoney(report, "%s x %d: $%d.%02d\n", item.sku, item.qty, lineAmount(item))
}

func writeSummary(report *strings.Builder, totals orderTotals) {
	writeSubtotal(report, totals.subtotal)
	writeDiscount(report, totals.discount)
	writeTax(report, totals.tax)
	writeShipping(report, totals.shipping)
	writeTotal(report, totals)
}

func writeSubtotal(report *strings.Builder, amount int) {
	writeMoney(report, "Subtotal: $%d.%02d\n", amount)
}

func writeDiscount(report *strings.Builder, amount int) {
	writeMoney(report, "Discount: $%d.%02d\n", amount)
}

func writeTax(report *strings.Builder, amount int) {
	writeMoney(report, "Tax: $%d.%02d\n", amount)
}

func writeShipping(report *strings.Builder, amount int) {
	writeMoney(report, "Shipping: $%d.%02d\n", amount)
}

func writeTotal(report *strings.Builder, totals orderTotals) {
	amount := totals.subtotal - totals.discount + totals.tax + totals.shipping
	writeMoney(report, "Total: $%d.%02d", amount)
}

func writeMoney(report *strings.Builder, format string, values ...interface{}) {
	amount := values[len(values)-1].(int)
	values[len(values)-1] = amount / 100
	values = append(values, amount%100)
	fmt.Fprintf(report, format, values...)
}
