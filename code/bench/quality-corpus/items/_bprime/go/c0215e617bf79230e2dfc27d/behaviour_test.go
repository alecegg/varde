package corpus

import "testing"

func TestValidIdent(t *testing.T) {
	cases := []struct {
		name string
		want bool
	}{
		{name: "x", want: true},
		{name: "total_1", want: true},
		{name: "", want: false},
		{name: "1abc", want: false},
		{name: "_abc", want: false},
		{name: "abc-def", want: false},
		{name: "AbC9_", want: true},
		{name: "abc def", want: false},
		{name: "Z9", want: true},
		{name: "café", want: false},
		{name: "123", want: false},
	}
	for _, testCase := range cases {
		if got := validIdent(testCase.name); got != testCase.want {
			t.Errorf("validIdent(%q) = %v, want %v", testCase.name, got, testCase.want)
		}
	}
}
