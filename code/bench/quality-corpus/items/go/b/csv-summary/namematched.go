package corpus

import (
	"errors"
	"fmt"
	"math"
	"math/big"
	"slices"
	"sort"
	"strconv"
)

var errInvalidRow = errors.New("invalid_row")

var noSummaries = []Summary{}

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

type Line struct {
	Product  string
	Quantity int
	Price    *big.Rat
}

type totals struct {
	counts   CountByProduct
	revenues RevenueByProduct
}

type CountByProduct map[string]int

type RevenueByProduct map[string]*big.Rat

// solution returns one summary row per product, or an error for an invalid row.
func solution(rows []Row) ([]Summary, error) {
	if anyRowRejected(rows) {
		return nil, errInvalidRow
	}
	return summariesForTotals(totalsByProduct(parsedLines(rows)), noSummaries), nil
}

func anyRowRejected(rows []Row) bool {
	return slices.ContainsFunc(rows, rowRejected)
}

func rowRejected(row Row) bool {
	return productNameRejected(row.Product) ||
		quantityOrPriceRejected(row.Quantity, row.UnitPrice)
}

func productNameRejected(product string) bool {
	return product == "" || slices.ContainsFunc([]byte(product), byteExceedsASCII)
}

func byteExceedsASCII(code byte) bool {
	return code > 127
}

func quantityOrPriceRejected(quantity int, price float64) bool {
	return quantity < 1 || math.IsNaN(price) || math.IsInf(price, 0) || price < 0
}

func parsedLines(rows []Row) (lines []Line) {
	for index := range rows {
		lines = append(lines, parsedLineAt(rows, index))
	}
	return
}

func parsedLineAt(rows []Row, index int) Line {
	row := rows[index]
	return Line{row.Product, row.Quantity, exactPriceOf(row.UnitPrice)}
}

func exactPriceOf(price float64) *big.Rat {
	value, _ := new(big.Rat).SetString(fmt.Sprint(price))
	return value
}

func totalsByProduct(lines []Line) totals {
	return totals{
		quantitiesByProduct(lines),
		revenuesByProduct(lines, make(map[string]*big.Rat, len(lines))),
	}
}

func quantitiesByProduct(lines []Line) CountByProduct {
	return accumulateQuantities(CountByProduct{}, lines)
}

func accumulateQuantities(counts CountByProduct, lines []Line) CountByProduct {
	for _, line := range lines {
		counts[line.Product] += line.Quantity
	}
	return counts
}

func revenuesByProduct(lines []Line, revenues RevenueByProduct) RevenueByProduct {
	for _, line := range lines {
		accumulateLine(revenues, line)
	}
	return revenues
}

func accumulateLine(revenues RevenueByProduct, line Line) {
	current := existingRevenue(revenues, line.Product)
	revenues[line.Product] = current.Add(current, lineRevenue(line))
}

func existingRevenue(revenues RevenueByProduct, product string) *big.Rat {
	if current := revenues[product]; current != nil {
		return current
	}
	return new(big.Rat)
}

func lineRevenue(line Line) *big.Rat {
	return new(big.Rat).Mul(line.Price, big.NewRat(int64(line.Quantity), 1))
}

func summariesForTotals(t totals, rows []Summary) []Summary {
	for _, name := range orderedProductNames(t) {
		rows = append(rows, summaryAtProduct(t, name))
	}
	return rows
}

func orderedProductNames(t totals) []string {
	names := productNames(t.revenues)
	sort.Strings(names)
	return names
}

func productNames[V any](totals map[string]V) (names []string) {
	for name := range totals {
		names = append(names, name)
	}
	return
}

func summaryAtProduct(t totals, name string) Summary {
	current := t.revenues[name]
	return Summary{name, t.counts[name], roundedRevenue(current)}
}

func roundedRevenue(revenue *big.Rat) float64 {
	amount, _ := strconv.ParseFloat(revenue.FloatString(2), 64)
	return amount
}
