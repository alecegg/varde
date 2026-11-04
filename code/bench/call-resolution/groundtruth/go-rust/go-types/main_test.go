package main

import (
	"go/parser"
	"testing"
)

func TestCalledName(t *testing.T) {
	tests := []struct {
		expr string
		want string
	}{
		{expr: "call", want: "call"},
		{expr: "pkg.call", want: "call"},
		{expr: "pkg.call[int]", want: "call"},
		{expr: "(call)", want: "call"},
	}
	for _, test := range tests {
		t.Run(test.expr, func(t *testing.T) {
			expr, err := parser.ParseExpr(test.expr)
			if err != nil {
				t.Fatal(err)
			}
			if got := calledName(expr); got != test.want {
				t.Fatalf("calledName(%q) = %q, want %q", test.expr, got, test.want)
			}
		})
	}
}
