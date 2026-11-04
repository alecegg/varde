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

type Line struct {
	Product  string
	Quantity int
	Revenue  *big.Rat
}

type Totals struct {
	Quantity int
	Revenue  big.Rat
}

// solution returns one summary row per product, or an error for an invalid row.
func solution(rows []Row) ([]Summary, error) {
	if !validRows(rows) {
		return nil, errInvalidRow
	}
	lines := priced(rows)
	totals := grouped(lines)
	names := orderedNames(totals)
	return summaryRows(totals, names), nil
}

func validRows(rows []Row) bool {
	for _, row := range rows {
		if row.Product == "" || row.Quantity < 1 || math.IsNaN(row.UnitPrice) ||
			math.IsInf(row.UnitPrice, 0) || row.UnitPrice < 0 {
			return false
		}
		for index := range row.Product {
			if row.Product[index] > 127 {
				return false
			}
		}
	}
	return true
}

func priced(rows []Row) []Line {
	lines := make([]Line, len(rows))
	for index, row := range rows {
		price, _ := new(big.Rat).SetString(fmt.Sprint(row.UnitPrice))
		price.Mul(price, big.NewRat(int64(row.Quantity), 1))
		lines[index] = Line{row.Product, row.Quantity, price}
	}
	return lines
}

func grouped(lines []Line) map[string]Totals {
	totals := map[string]Totals{}
	for _, line := range lines {
		current := totals[line.Product]
		current.Quantity += line.Quantity
		current.Revenue.Add(&current.Revenue, line.Revenue)
		totals[line.Product] = current
	}
	return totals
}

func orderedNames(totals map[string]Totals) []string {
	names := make([]string, 0, len(totals))
	for name := range totals {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func summaryRows(totals map[string]Totals, names []string) []Summary {
	rows := make([]Summary, 0, len(names))
	for _, name := range names {
		current := totals[name]
		amount, _ := strconv.ParseFloat(current.Revenue.FloatString(2), 64)
		rows = append(rows, Summary{name, current.Quantity, amount})
	}
	return rows
}
