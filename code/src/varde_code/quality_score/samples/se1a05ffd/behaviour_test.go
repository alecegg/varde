package original

import (
	"strings"
	"testing"
)

func TestValidateOrder(t *testing.T) {
	valid := [][]string{{"PEN,1"}, {"BOOK,99", "BAG,2"}}
	for _, rows := range valid {
		if err := ValidateOrder(rows); err != nil {
			t.Errorf("ValidateOrder(%v): %v", rows, err)
		}
	}
	invalid := [][]string{
		{}, {"PEN,0"}, {"PEN,100"}, {"PEN,x"}, {"PEN"}, {"PEN,1,2"},
		{"BAD,1"}, {"PEN,1", "PEN,2"}, {" PEN,1"}, {"PEN,1 "},
	}
	for _, rows := range invalid {
		if err := ValidateOrder(rows); err == nil {
			t.Errorf("ValidateOrder(%v) expected error", rows)
		}
	}
	if err := ValidateOrder(make([]string, 21)); err == nil {
		t.Error("expected row limit error")
	}
}

func TestProcessOrderPricing(t *testing.T) {
	cases := []struct {
		rows []string
		want []string
	}{
		{[]string{"PEN,1"}, []string{"PEN x 1: $1.25", "Subtotal: $1.25", "Discount: $0.00", "Tax: $0.10", "Shipping: $0.00", "Total: $1.35"}},
		{[]string{"BOOK,3"}, []string{"BOOK x 3: $25.50", "Discount: $1.28", "Tax: $1.94", "Shipping: $0.00", "Total: $26.16"}},
		{[]string{"BAG,3"}, []string{"BAG x 3: $72.00", "Discount: $3.60", "Tax: $5.47", "Shipping: $4.95", "Total: $78.82"}},
		{[]string{"BAG,4"}, []string{"Subtotal: $96.00", "Discount: $9.60", "Tax: $6.91", "Shipping: $9.95", "Total: $103.26"}},
		{[]string{"PEN,20"}, []string{"Subtotal: $25.00", "Discount: $1.25", "Tax: $1.90", "Shipping: $0.00", "Total: $25.65"}},
		{[]string{"PEN,19"}, []string{"Subtotal: $23.75", "Discount: $0.00", "Shipping: $0.00", "Total: $25.65"}},
	}
	for _, tc := range cases {
		got, err := ProcessOrder(tc.rows)
		if err != nil {
			t.Fatalf("ProcessOrder(%v): %v", tc.rows, err)
		}
		for _, line := range tc.want {
			if !strings.Contains(got, line) {
				t.Errorf("report for %v missing %q:\n%s", tc.rows, line, got)
			}
		}
	}
}

func TestProcessOrderErrorsAndOrder(t *testing.T) {
	if _, err := ProcessOrder([]string{"NOPE,1"}); err == nil {
		t.Error("expected invalid order error")
	}
	got, err := ProcessOrder([]string{"BAG,1", "PEN,2"})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Index(got, "BAG x 1") > strings.Index(got, "PEN x 2") {
		t.Errorf("item order changed:\n%s", got)
	}
	if strings.Count(got, "Subtotal:") != 1 || strings.Count(got, "Total:") != 1 {
		t.Errorf("summary lines missing or duplicated:\n%s", got)
	}
}
