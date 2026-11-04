package corpus

import (
	"fmt"
	"math"
	"math/big"
	"math/rand"
	"sort"
	"strconv"
	"testing"
	"time"
)

func decimalOf(value float64) *big.Rat {
	text := strconv.FormatFloat(value, 'f', -1, 64)
	exact, ok := new(big.Rat).SetString(text)
	if !ok {
		panic("test case is not an exact decimal: " + text)
	}
	return exact
}

func halfUpCents(total *big.Rat) *big.Int {
	scaled := new(big.Rat).Mul(total, big.NewRat(100, 1))
	whole := new(big.Int)
	remainder := new(big.Int)
	whole.QuoRem(scaled.Num(), scaled.Denom(), remainder)
	twice := new(big.Int).Abs(remainder)
	twice.Lsh(twice, 1)
	if twice.Cmp(scaled.Denom()) < 0 {
		return whole
	}
	if scaled.Num().Sign() < 0 {
		return whole.Sub(whole, big.NewInt(1))
	}
	return whole.Add(whole, big.NewInt(1))
}

func centsAmount(cents *big.Int) float64 {
	amount, _ := new(big.Rat).SetFrac(cents, big.NewInt(100)).Float64()
	return amount
}

func referenceSummary(rows []Row) []Summary {
	counts := map[string]int{}
	revenues := map[string]*big.Rat{}
	for _, row := range rows {
		counts[row.Product] += row.Quantity
		total, known := revenues[row.Product]
		if !known {
			total = new(big.Rat)
			revenues[row.Product] = total
		}
		line := new(big.Rat).Mul(decimalOf(row.UnitPrice), big.NewRat(int64(row.Quantity), 1))
		total.Add(total, line)
	}
	names := make([]string, 0, len(revenues))
	for name := range revenues {
		names = append(names, name)
	}
	sort.Strings(names)
	summary := make([]Summary, 0, len(names))
	for _, name := range names {
		cents := halfUpCents(revenues[name])
		summary = append(summary, Summary{name, counts[name], centsAmount(cents)})
	}
	return summary
}

func sameSummary(got, want []Summary) bool {
	if len(got) != len(want) {
		return false
	}
	for index := range got {
		if got[index] != want[index] {
			return false
		}
	}
	return true
}

func TestCsvSummaryBankCases(t *testing.T) {
	cases := []struct {
		rows []Row
		want []Summary
	}{
		{[]Row{{"Tea", 2, 3}}, []Summary{{"Tea", 2, 6}}},
		{[]Row{}, []Summary{}},
		{nil, []Summary{}},
		{[]Row{{"Pen", 3, 1.2}, {"Book", 1, 8}}, []Summary{{"Book", 1, 8}, {"Pen", 3, 3.6}}},
		{[]Row{{"Tea", 1, 2}, {"Tea", 4, 2.5}}, []Summary{{"Tea", 5, 12}}},
		{[]Row{{"A", 1, 0}}, []Summary{{"A", 1, 0}}},
		{[]Row{{"z", 2, 1.11}, {"a", 2, 1.11}}, []Summary{{"a", 2, 2.22}, {"z", 2, 2.22}}},
		{
			[]Row{{"Mug", 2, 4.5}, {"Mug", 1, 4.5}, {"Bag", 1, 7}},
			[]Summary{{"Bag", 1, 7}, {"Mug", 3, 13.5}},
		},
		{[]Row{{"x", 10, 0.05}}, []Summary{{"x", 10, 0.5}}},
		{[]Row{{"same", 1, 1}, {"Same", 1, 2}}, []Summary{{"Same", 1, 2}, {"same", 1, 1}}},
		{[]Row{{"\x7f", 1, 0}}, []Summary{{"\x7f", 1, 0}}},
		{[]Row{{"K", 7, 2.35}}, []Summary{{"K", 7, 16.45}}},
	}
	for _, testCase := range cases {
		got, err := solution(testCase.rows)
		if err != nil {
			t.Fatalf("solution(%v) returned %v", testCase.rows, err)
		}
		if got == nil {
			t.Fatalf("solution(%v) returned a nil summary, want an empty slice", testCase.rows)
		}
		if !sameSummary(got, testCase.want) {
			t.Errorf("solution(%v) = %v, want %v", testCase.rows, got, testCase.want)
		}
		want := referenceSummary(testCase.rows)
		if !sameSummary(got, want) {
			t.Errorf("solution(%v) = %v, reference %v", testCase.rows, got, want)
		}
	}
}

func TestCsvSummaryRoundingCases(t *testing.T) {
	cases := []struct {
		rows []Row
		want []Summary
	}{
		{[]Row{{"p", 1, 1.005}}, []Summary{{"p", 1, 1.01}}},
		{[]Row{{"p", 1, 2.675}}, []Summary{{"p", 1, 2.68}}},
		{[]Row{{"p", 2, 1.005}}, []Summary{{"p", 2, 2.01}}},
		{[]Row{{"p", 3, 0.005}}, []Summary{{"p", 3, 0.02}}},
		{[]Row{{"p", 1, 0.0049}}, []Summary{{"p", 1, 0}}},
		{[]Row{{"p", 7, 0.001}}, []Summary{{"p", 7, 0.01}}},
		{[]Row{{"p", 1, 16.6}}, []Summary{{"p", 1, 16.6}}},
		{[]Row{{"p", 3, 1.004}}, []Summary{{"p", 3, 3.01}}},
	}
	for _, testCase := range cases {
		got, err := solution(testCase.rows)
		if err != nil {
			t.Fatalf("solution(%v) returned %v", testCase.rows, err)
		}
		if !sameSummary(got, testCase.want) {
			t.Errorf("solution(%v) = %v, want %v", testCase.rows, got, testCase.want)
		}
		if want := referenceSummary(testCase.rows); !sameSummary(got, want) {
			t.Errorf("solution(%v) = %v, reference %v", testCase.rows, got, want)
		}
	}
}

func TestCsvSummarySubCentTotals(t *testing.T) {
	cases := []struct {
		rows []Row
		want float64
	}{
		{[]Row{{"p", 1, 0.004}, {"p", 1, 0.004}, {"p", 1, 0.004}}, 0.01},
		{[]Row{{"p", 3, 0.004}}, 0.01},
		{[]Row{{"p", 2, 0.004}, {"p", 4, 0.004}}, 0.02},
		{[]Row{{"p", 1, 0.006}, {"p", 1, 0.006}, {"p", 1, 0.003}}, 0.02},
		{[]Row{{"p", 5, 0.001}, {"p", 5, 0.001}}, 0.01},
	}
	for _, testCase := range cases {
		got, err := solution(testCase.rows)
		if err != nil {
			t.Fatalf("solution(%v) returned %v", testCase.rows, err)
		}
		if len(got) != 1 || got[0].Revenue != testCase.want {
			t.Fatalf("solution(%v) = %v, want a single product at %v", testCase.rows, got, testCase.want)
		}
		if want := referenceSummary(testCase.rows); !sameSummary(got, want) {
			t.Errorf("solution(%v) = %v, reference %v", testCase.rows, got, want)
		}
	}
}

func TestCsvSummaryLargeRevenue(t *testing.T) {
	cases := []struct {
		rows []Row
		want float64
	}{
		{[]Row{{"Big", 1, 9.3e16}}, 9.3e16},
		{[]Row{{"Wide", 3, 123456789012.34}}, 370370367037.02},
		{[]Row{{"Huge", 1000000, 1e13}}, 1e19},
		{[]Row{{"Tall", 7, 9876543210987.65}}, 69135802476913.55},
	}
	for _, testCase := range cases {
		got, err := solution(testCase.rows)
		if err != nil {
			t.Fatalf("solution(%v) returned %v", testCase.rows, err)
		}
		if len(got) != 1 || got[0].Revenue != testCase.want {
			t.Fatalf("solution(%v) = %v, want %v", testCase.rows, got, testCase.want)
		}
		if want := referenceSummary(testCase.rows); !sameSummary(got, want) {
			t.Errorf("solution(%v) = %v, reference %v", testCase.rows, got, want)
		}
	}
}

func TestCsvSummaryInvalidRows(t *testing.T) {
	cases := [][]Row{
		{{"", 1, 2}},
		{{"naïve", 1, 2}},
		{{"Tea", 0, 1}},
		{{"Tea", -1, 1}},
		{{"Tea", 1, math.NaN()}},
		{{"Tea", 1, math.Inf(1)}},
		{{"Tea", 1, math.Inf(-1)}},
		{{"Tea", 1, -0.01}},
		{{"é", 1, 1}},
		{{"Tea", 1, 1}, {"", 1, 1}},
		{{"Tea", 1, 1}, {"Tea", 0, 1}},
		{{"", 1, 1}, {"Tea", 1, math.NaN()}},
		{{"Tea", 1, math.NaN()}, {"", 1, 1}},
	}
	for _, rows := range cases {
		got, err := solution(rows)
		if err != errInvalidRow {
			t.Errorf("solution(%v) error = %v, want %v", rows, err, errInvalidRow)
		}
		if got != nil {
			t.Errorf("solution(%v) = %v, want no summary", rows, got)
		}
	}
}

func TestCsvSummaryLargeInput(t *testing.T) {
	generator := rand.New(rand.NewSource(20261017))
	rows := make([]Row, 0, 3000)
	for index := 0; index < 3000; index++ {
		product := fmt.Sprintf("P%02d", generator.Intn(60))
		price := float64(generator.Intn(1000000)) / 1000
		rows = append(rows, Row{product, 1 + generator.Intn(99), price})
	}
	shuffled := make([]Row, len(rows))
	copy(shuffled, rows)
	generator.Shuffle(len(shuffled), func(left, right int) {
		shuffled[left], shuffled[right] = shuffled[right], shuffled[left]
	})
	order := make([]string, 0, len(shuffled))
	for _, row := range shuffled {
		order = append(order, row.Product)
	}
	if sort.StringsAreSorted(order) {
		t.Fatal("the large case must start in scrambled product order")
	}
	got, err := solution(shuffled)
	if err != nil {
		t.Fatalf("solution(large) returned %v", err)
	}
	want := referenceSummary(rows)
	if !sameSummary(got, want) {
		t.Fatalf("solution(large) = %v, want %v", got, want)
	}
}

func TestCsvSummaryRandomRows(t *testing.T) {
	generator := rand.New(rand.NewSource(11))
	for round := 0; round < 2000; round++ {
		rows := make([]Row, 0, 8)
		for index := 0; index < generator.Intn(9); index++ {
			product := fmt.Sprintf("p%02d", generator.Intn(7))
			price := float64(generator.Intn(500000)) / 1000
			rows = append(rows, Row{product, 1 + generator.Intn(40), price})
		}
		got, err := solution(rows)
		if err != nil {
			t.Fatalf("round %d: solution(%v) returned %v", round, rows, err)
		}
		if got == nil {
			t.Fatalf("round %d: solution(%v) returned a nil summary", round, rows)
		}
		want := referenceSummary(rows)
		if !sameSummary(got, want) {
			t.Fatalf("round %d: solution(%v) = %v, want %v", round, rows, got, want)
		}
	}
}

func TestCsvSummaryHundredThousandRows(t *testing.T) {
	const rowCount = 100000
	rows := make([]Row, 0, rowCount)
	for index := rowCount - 1; index >= 0; index-- {
		product := fmt.Sprintf("P%06d", index)
		rows = append(rows, Row{product, 1, 1})
	}
	order := make([]string, 0, len(rows))
	for _, row := range rows {
		order = append(order, row.Product)
	}
	if sort.StringsAreSorted(order) {
		t.Fatal("the large case must start in scrambled product order")
	}
	type result struct {
		rows []Summary
		err  error
	}
	completed := make(chan result, 1)
	go func() {
		got, err := solution(rows)
		completed <- result{got, err}
	}()
	timer := time.NewTimer(4 * time.Second)
	defer timer.Stop()
	var got []Summary
	select {
	case outcome := <-completed:
		got = outcome.rows
		if outcome.err != nil {
			t.Fatalf("solution with %d unique rows returned %v", rowCount, outcome.err)
		}
	case <-timer.C:
		t.Fatalf("solution with %d unique rows exceeded 4s", rowCount)
	}
	gotOrder := make([]string, 0, len(got))
	for _, row := range got {
		gotOrder = append(gotOrder, row.Product)
	}
	if !sort.StringsAreSorted(gotOrder) {
		t.Fatal("solution with 100000 rows returned products out of order")
	}
	want := referenceSummary(rows)
	if !sameSummary(got, want) {
		t.Fatal("solution with 100000 rows does not match the exact reference")
	}
}
