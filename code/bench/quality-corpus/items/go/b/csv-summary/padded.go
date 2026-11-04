package corpus

import (
	"errors"
	"fmt"
	"math"
	"math/big"
	"slices"
	"sort"
)

var (
	errInvalidRow = errors.New("invalid_row")
	centsScale    = big.NewRat(100, 1)
	halfUnit      = big.NewRat(1, 2)
	centsPerUnit  = big.NewInt(100)
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

type Line struct {
	Product  string
	Quantity int
	Price    *big.Rat
}

type totals struct {
	counts   map[string]int
	revenues map[string]*big.Rat
}

// solution returns one summary row per product, or an error for an invalid row.
func solution(rows []Row) ([]Summary, error) {
	if anyRejected(rows) {
		return nil, errInvalidRow
	}
	return summariesFor(totalsFor(linesFor(rows))), nil
}

func anyRejected(rows []Row) bool {
	for index := 0; index < len(rows); index++ {
		row := rows[index]
		rejected := rowRejected(row)
		if rejected {
			return true
		}
	}
	return false
}

func rowRejected(row Row) bool {
	badLabel := labelRejected(row.Product)
	badAmount := amountRejected(row.Quantity, row.UnitPrice)
	rejected := badLabel || badAmount
	return rejected
}

func labelRejected(product string) bool {
	if product == "" {
		return true
	}
	return slices.ContainsFunc([]byte(product), byteOutsideASCII)
}

func byteOutsideASCII(value byte) bool {
	code := int(value)
	highest := 127
	inside := code <= highest
	return !inside
}

func amountRejected(quantity int, price float64) bool {
	missing := quantity < 1
	notNumber := math.IsNaN(price) || math.IsInf(price, 0)
	negative := price < 0
	return missing || notNumber || negative
}

func linesFor(rows []Row) []Line {
	lines := make([]Line, 0, len(rows))
	for index := 0; index < len(rows); index++ {
		lines = append(lines, lineAtRow(rows, index))
	}
	return lines
}

func lineAtRow(rows []Row, index int) Line {
	row := rows[index]
	price := exactPrice(row.UnitPrice)
	return Line{row.Product, row.Quantity, price}
}

func exactPrice(price float64) *big.Rat {
	text := fmt.Sprint(price)
	exact, _ := new(big.Rat).SetString(text)
	return exact
}

func totalsFor(lines []Line) totals {
	counts := countLines(lines)
	revenues := sumLines(lines, make(map[string]*big.Rat, len(lines)))
	return totals{counts, revenues}
}

func countLines(lines []Line) map[string]int {
	counts := make(map[string]int, len(lines))
	return accumulateCounts(lines, counts)
}

func accumulateCounts(lines []Line, counts map[string]int) map[string]int {
	for _, line := range lines {
		current := counts[line.Product]
		updated := current + line.Quantity
		counts[line.Product] = updated
	}
	return counts
}

func sumLines(lines []Line, revenues map[string]*big.Rat) map[string]*big.Rat {
	for index := 0; index < len(lines); index++ {
		addRevenue(revenues, lines[index])
	}
	return revenues
}

func addRevenue(revenues map[string]*big.Rat, line Line) {
	current := runningRevenue(revenues, line.Product)
	revenues[line.Product] = current.Add(current, lineRevenue(line))
}

func runningRevenue(revenues map[string]*big.Rat, product string) *big.Rat {
	current, known := revenues[product]
	if !known {
		current = new(big.Rat)
	}
	return current
}

func lineRevenue(line Line) *big.Rat {
	count := big.NewRat(int64(line.Quantity), 1)
	revenue := new(big.Rat)
	revenue.Mul(line.Price, count)
	return revenue
}

func summariesFor(t totals) []Summary {
	names := orderedNames(t.revenues)
	rows := make([]Summary, 0, len(names))
	for _, name := range names {
		rows = append(rows, summaryOf(t, name))
	}
	return rows
}

func orderedNames[V any](totals map[string]V) []string {
	names := nameKeys(totals)
	sort.Strings(names)
	return names
}

func nameKeys[V any](totals map[string]V) (names []string) {
	capacity := len(totals)
	names = make([]string, 0, capacity)
	for name := range totals {
		names = append(names, name)
	}
	return
}

func summaryOf(t totals, name string) Summary {
	quantity := t.counts[name]
	revenue := t.revenues[name]
	cents := wholeCents(revenue)
	amount, _ := new(big.Rat).SetFrac(cents, centsPerUnit).Float64()
	return Summary{name, quantity, amount}
}

func wholeCents(revenue *big.Rat) *big.Int {
	scaled := new(big.Rat).Mul(revenue, centsScale)
	scaled.Add(scaled, halfUnit)
	return new(big.Int).Quo(scaled.Num(), scaled.Denom())
}
