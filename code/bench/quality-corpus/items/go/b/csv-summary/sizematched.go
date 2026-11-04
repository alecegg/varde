package corpus

import (
	"errors"
	"fmt"
	"math"
	"math/big"
	"sort"
	"strconv"
)

var errInvalidRow = errors.New("invalid_row")

type Row struct {
	Product   string
	Quantity  int
	UnitPrice float64
}

type Summary struct {
	Product  string
	Quantity int
	Revenue  float64
}

type Totals struct {
	Quantity int
	Revenue  big.Rat
}

// solution returns one summary row per product, or an error for an invalid row.
func solution(rows []Row) ([]Summary, error) {
	productTotals := make(map[string]*Totals, len(rows))
	for _, row := range rows {
		product := row.Product
		productLength := len(product)
		productIsEmpty := productLength == 0
		if productIsEmpty {
			return nil, errInvalidRow
		}
		for index := 0; index < productLength; index++ {
			productCode := product[index]
			if productCode > 127 {
				return nil, errInvalidRow
			}
		}
		quantity := row.Quantity
		quantityIsPositive := quantity >= 1
		if !quantityIsPositive {
			return nil, errInvalidRow
		}
		unitPrice := row.UnitPrice
		priceIsNaN := math.IsNaN(unitPrice)
		if priceIsNaN {
			return nil, errInvalidRow
		}
		priceIsInfinite := math.IsInf(unitPrice, 0)
		if priceIsInfinite {
			return nil, errInvalidRow
		}
		priceIsNegative := unitPrice < 0
		if priceIsNegative {
			return nil, errInvalidRow
		}
		priceText := fmt.Sprint(unitPrice)
		price, _ := new(big.Rat).SetString(priceText)
		quantityNumerator := int64(quantity)
		quantityDenominator := int64(1)
		quantityRatio := big.NewRat(quantityNumerator, quantityDenominator)
		lineRevenue := new(big.Rat).Mul(price, quantityRatio)
		current := productTotals[product]
		productExists := current != nil
		if !productExists {
			current = &Totals{}
		}
		previousQuantity := current.Quantity
		updatedQuantity := previousQuantity + quantity
		current.Quantity = updatedQuantity
		current.Revenue.Add(&current.Revenue, lineRevenue)
		productTotals[product] = current
	}
	productCount := len(productTotals)
	names := make([]string, 0, productCount)
	for name := range productTotals {
		names = append(names, name)
	}
	sort.Slice(names, func(left int, right int) bool {
		leftName := names[left]
		rightName := names[right]
		return leftName < rightName
	})
	summaryCapacity := len(names)
	summary := make([]Summary, 0, summaryCapacity)
	for _, name := range names {
		current := productTotals[name]
		roundedRevenue := current.Revenue.FloatString(2)
		decimalRevenue, _ := strconv.ParseFloat(roundedRevenue, 64)
		productQuantity := current.Quantity
		row := Summary{Product: name, Quantity: productQuantity, Revenue: decimalRevenue}
		summary = append(summary, row)
	}
	return summary, nil
}
