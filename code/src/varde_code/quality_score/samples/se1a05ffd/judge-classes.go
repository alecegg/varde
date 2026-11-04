package original

import (
	"fmt"
	"strconv"
	"strings"
)

type orderItem struct {
	sku      string
	quantity int
	unitCost int
}

type productCatalog interface {
	unitCost(sku string) (int, bool)
}

type inventoryCatalog struct{}

func (inventoryCatalog) unitCost(sku string) (int, bool) {
	switch sku {
	case "PEN":
		return 125, true
	case "BOOK":
		return 850, true
	case "BAG":
		return 2400, true
	default:
		return 0, false
	}
}

type orderParser struct {
	catalog productCatalog
}

func (p orderParser) parse(lines []string) ([]orderItem, error) {
	if len(lines) == 0 || len(lines) > 20 {
		return nil, fmt.Errorf("order must contain 1 to 20 rows")
	}

	items := make([]orderItem, 0, len(lines))
	seen := make(map[string]bool, len(lines))
	for _, row := range lines {
		parts := strings.Split(row, ",")
		if len(parts) != 2 {
			return nil, fmt.Errorf("invalid row %q", row)
		}
		cost, ok := p.catalog.unitCost(parts[0])
		if !ok {
			return nil, fmt.Errorf("unknown sku %q", parts[0])
		}
		if seen[parts[0]] {
			return nil, fmt.Errorf("duplicate sku %q", parts[0])
		}
		quantity, err := strconv.Atoi(parts[1])
		if err != nil || quantity < 1 || quantity > 99 {
			return nil, fmt.Errorf("invalid quantity %q", parts[1])
		}
		seen[parts[0]] = true
		items = append(items, orderItem{sku: parts[0], quantity: quantity, unitCost: cost})
	}
	return items, nil
}

type discountPolicy interface {
	amount(subtotal int) int
}

type thresholdDiscount struct{}

func (thresholdDiscount) amount(subtotal int) int {
	if subtotal >= 7500 {
		return roundedPercent(subtotal, 10)
	}
	if subtotal >= 2500 {
		return roundedPercent(subtotal, 5)
	}
	return 0
}

type shippingPolicy interface {
	amount(discountedSubtotal int) int
}

type thresholdShipping struct{}

func (thresholdShipping) amount(discountedSubtotal int) int {
	if discountedSubtotal < 2500 {
		return 0
	}
	if discountedSubtotal < 7500 {
		return 495
	}
	return 995
}

type orderPrice struct {
	subtotal int
	discount int
	tax      int
	shipping int
	total    int
}

type orderPricer struct {
	discounts discountPolicy
	shipping  shippingPolicy
}

func (p orderPricer) price(items []orderItem) orderPrice {
	subtotal := 0
	for _, item := range items {
		subtotal += item.unitCost * item.quantity
	}
	discount := p.discounts.amount(subtotal)
	discountedSubtotal := subtotal - discount
	tax := roundedPercent(discountedSubtotal, 8)
	shipping := p.shipping.amount(discountedSubtotal)
	return orderPrice{
		subtotal: subtotal,
		discount: discount,
		tax:      tax,
		shipping: shipping,
		total:    discountedSubtotal + tax + shipping,
	}
}

type orderReport struct{}

func (orderReport) render(items []orderItem, price orderPrice) string {
	var output strings.Builder
	for _, item := range items {
		writeMoneyLine(&output, fmt.Sprintf("%s x %d", item.sku, item.quantity), item.unitCost*item.quantity)
	}
	writeMoneyLine(&output, "Subtotal", price.subtotal)
	writeMoneyLine(&output, "Discount", price.discount)
	writeMoneyLine(&output, "Tax", price.tax)
	writeMoneyLine(&output, "Shipping", price.shipping)
	writeMoneyLine(&output, "Total", price.total)
	return strings.TrimSuffix(output.String(), "\n")
}

func writeMoneyLine(output *strings.Builder, label string, cents int) {
	fmt.Fprintf(output, "%s: $%d.%02d\n", label, cents/100, cents%100)
}

func roundedPercent(value, percent int) int {
	return (value*percent + 50) / 100
}

type inventoryOrderService struct {
	parser orderParser
	pricer orderPricer
	report orderReport
}

func newInventoryOrderService() inventoryOrderService {
	return inventoryOrderService{
		parser: orderParser{catalog: inventoryCatalog{}},
		pricer: orderPricer{discounts: thresholdDiscount{}, shipping: thresholdShipping{}},
		report: orderReport{},
	}
}

func (s inventoryOrderService) validate(lines []string) error {
	_, err := s.parser.parse(lines)
	return err
}

func (s inventoryOrderService) process(lines []string) (string, error) {
	items, err := s.parser.parse(lines)
	if err != nil {
		return "", err
	}
	price := s.pricer.price(items)
	return s.report.render(items, price), nil
}

func ValidateOrder(lines []string) error {
	return newInventoryOrderService().validate(lines)
}

func ProcessOrder(lines []string) (string, error) {
	return newInventoryOrderService().process(lines)
}
