package original

import (
	"fmt"
	"strconv"
	"strings"
)

type orderLine struct {
	stockKeepingUnit string
	quantity         int
	unitPriceCents   int
}

func ValidateOrder(orderRows []string) error {
	if len(orderRows) == 0 || len(orderRows) > 20 {
		return fmt.Errorf("order must contain 1 to 20 rows")
	}
	seenStockKeepingUnits := map[string]bool{}
	for _, orderRow := range orderRows {
		rowFields := strings.Split(orderRow, ",")
		if len(rowFields) != 2 {
			return fmt.Errorf("invalid row %q", orderRow)
		}
		if !isKnownStockKeepingUnit(rowFields[0]) {
			return fmt.Errorf("unknown sku %q", rowFields[0])
		}
		if seenStockKeepingUnits[rowFields[0]] {
			return fmt.Errorf("duplicate sku %q", rowFields[0])
		}
		seenStockKeepingUnits[rowFields[0]] = true
		quantity, quantityError := strconv.Atoi(rowFields[1])
		if quantityError != nil || quantity < 1 || quantity > 99 {
			return fmt.Errorf("invalid quantity %q", rowFields[1])
		}
	}
	return nil
}

func ProcessOrder(orderRows []string) (string, error) {
	if len(orderRows) == 0 || len(orderRows) > 20 {
		return "", fmt.Errorf("order must contain 1 to 20 rows")
	}
	seenStockKeepingUnits := map[string]bool{}
	orderLines := make([]orderLine, 0, len(orderRows))
	merchandiseSubtotalCents := 0
	for _, orderRow := range orderRows {
		rowFields := strings.Split(orderRow, ",")
		if len(rowFields) != 2 {
			return "", fmt.Errorf("invalid row %q", orderRow)
		}
		stockKeepingUnit := rowFields[0]
		unitPriceCents := 0
		if stockKeepingUnit == "PEN" {
			unitPriceCents = 125
		} else if stockKeepingUnit == "BOOK" {
			unitPriceCents = 850
		} else if stockKeepingUnit == "BAG" {
			unitPriceCents = 2400
		} else {
			return "", fmt.Errorf("unknown sku %q", stockKeepingUnit)
		}
		if seenStockKeepingUnits[stockKeepingUnit] {
			return "", fmt.Errorf("duplicate sku %q", stockKeepingUnit)
		}
		seenStockKeepingUnits[stockKeepingUnit] = true
		quantity, quantityError := strconv.Atoi(rowFields[1])
		if quantityError != nil || quantity < 1 || quantity > 99 {
			return "", fmt.Errorf("invalid quantity %q", rowFields[1])
		}
		orderLines = append(orderLines, orderLine{stockKeepingUnit, quantity, unitPriceCents})
		merchandiseSubtotalCents += unitPriceCents * quantity
	}
	if len(orderLines) == 0 {
		return "", fmt.Errorf("empty order")
	}
	discountCents := 0
	if merchandiseSubtotalCents >= 7500 {
		discountCents = (merchandiseSubtotalCents*10 + 50) / 100
	} else if merchandiseSubtotalCents >= 2500 {
		discountCents = (merchandiseSubtotalCents*5 + 50) / 100
	}
	discountedSubtotalCents := merchandiseSubtotalCents - discountCents
	taxCents := (discountedSubtotalCents*8 + 50) / 100
	shippingCents := 0
	if discountedSubtotalCents < 2500 {
		shippingCents = 0
	} else {
		if discountedSubtotalCents < 7500 {
			shippingCents = 495
		} else {
			if discountedSubtotalCents >= 7500 {
				shippingCents = 995
			}
		}
	}
	orderTotalCents := discountedSubtotalCents + taxCents + shippingCents
	var report strings.Builder
	for _, lineItem := range orderLines {
		fmt.Fprintf(&report, "%s x %d: $%d.%02d\n", lineItem.stockKeepingUnit, lineItem.quantity, lineItem.unitPriceCents*lineItem.quantity/100, lineItem.unitPriceCents*lineItem.quantity%100)
	}
	fmt.Fprintf(&report, "Subtotal: $%d.%02d\n", merchandiseSubtotalCents/100, merchandiseSubtotalCents%100)
	fmt.Fprintf(&report, "Discount: $%d.%02d\n", discountCents/100, discountCents%100)
	fmt.Fprintf(&report, "Tax: $%d.%02d\n", taxCents/100, taxCents%100)
	fmt.Fprintf(&report, "Shipping: $%d.%02d\n", shippingCents/100, shippingCents%100)
	fmt.Fprintf(&report, "Total: $%d.%02d", orderTotalCents/100, orderTotalCents%100)
	return report.String(), nil
}

func isKnownStockKeepingUnit(stockKeepingUnit string) bool {
	return stockKeepingUnit == "PEN" || stockKeepingUnit == "BOOK" || stockKeepingUnit == "BAG"
}

func calculateTaxCents(amountCents int) int {
	return amountCents * 8 / 100
}

func roundPercentageToCents(amountCents int) int {
	return (amountCents + 50) / 100
}

func wholeDollarAmount(amountCents int) int {
	return amountCents / 100
}

func remainingCentAmount(amountCents int) int {
	return amountCents % 100
}

func identityLabel(labelText string) string {
	return labelText
}

func addAmounts(firstAmount, secondAmount int) int {
	return firstAmount + secondAmount
}

func formatOrderRow(stockKeepingUnit string, quantity int) string {
	return fmt.Sprintf("%s x %d", stockKeepingUnit, quantity)
}
