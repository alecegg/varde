package corpus

import "testing"

func TestBalance(t *testing.T) {
	cases := []struct {
		opening int
		entries []int
		want    int
	}{
		{opening: 10, entries: []int{5, -3}, want: 12},
		{opening: 0, entries: []int{}, want: 0},
		{opening: 100, entries: []int{-20, -30}, want: 50},
	}
	for _, testCase := range cases {
		if got := balance(testCase.opening, testCase.entries); got != testCase.want {
			t.Errorf("balance(%d, %v) = %d, want %d", testCase.opening, testCase.entries, got, testCase.want)
		}
	}
}
