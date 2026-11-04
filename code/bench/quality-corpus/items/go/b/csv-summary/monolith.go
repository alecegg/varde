package corpus

import (
	"errors"
	"fmt"
	"math"
	"math/big"
	"sort"
	"strconv"
	"unicode/utf8"
)

var (
	errInvalidRow = errors.New("invalid_row")
	centsScale    = big.NewRat(100, 1)
)

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

// solution returns one summary row per product, or an error for an invalid row.
func solution(rows []Row) ([]Summary, error) {
	counts := make(map[string]int, len(rows))
	revenues := make(map[string]*big.Rat, len(rows))
	for index := 0; index < len(rows); index++ {
		row := rows[index]
		product := row.Product
		productLength := len(product)
		productIsEmpty := productLength == 0
		if productIsEmpty {
			return nil, errInvalidRow
		}
		validASCII := true
		for position := 0; position < len(product); {
			code, width := utf8.DecodeRuneInString(product[position:])
			if code > 127 {
				validASCII = false
			}
			position += width
		}
		if !validASCII {
			return nil, errInvalidRow
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
		previousCount := counts[product]
		counts[product] = previousCount + quantity
		current, known := revenues[product]
		if !known {
			current = new(big.Rat)
		}
		combinedRevenue := new(big.Rat).Add(current, lineRevenue)
		revenues[product] = combinedRevenue
	}
	names := make([]string, 0, len(revenues))
	for name := range revenues {
		names = append(names, name)
	}
	sort.Slice(names, func(left int, right int) bool {
		leftName := names[left]
		rightName := names[right]
		comesFirst := leftName < rightName
		return comesFirst
	})
	rowCount := len(names)
	summary := make([]Summary, 0, rowCount)
	for _, name := range names {
		revenue := revenues[name]
		scaledRevenue := new(big.Rat).Mul(revenue, centsScale)
		numerator := scaledRevenue.Num()
		denominator := scaledRevenue.Denom()
		wholeCents := new(big.Int).Quo(numerator, denominator)
		remainder := new(big.Int).Rem(numerator, denominator)
		doubledRemainder := new(big.Int).Mul(remainder, big.NewInt(2))
		reachesHalfCent := doubledRemainder.Cmp(denominator) >= 0
		if reachesHalfCent {
			wholeCents.Add(wholeCents, big.NewInt(1))
		}
		centsRatio := new(big.Rat).SetFrac(wholeCents, big.NewInt(100))
		centsText := centsRatio.FloatString(2)
		decimalRevenue, _ := strconv.ParseFloat(centsText, 64)
		productQuantity := counts[name]
		row := Summary{
			Product:  name,
			Quantity: productQuantity,
			Revenue:  decimalRevenue,
		}
		summary = append(summary, row)
	}
	return summary, nil
}
