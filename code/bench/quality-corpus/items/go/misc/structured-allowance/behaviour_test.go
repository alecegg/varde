package corpus

import "testing"

func TestRemaining(t *testing.T) {
	cases := []struct {
		start    int
		expenses []int
		want     int
	}{
		{start: 100, expenses: []int{10, 20}, want: 70},
		{start: 50, expenses: []int{}, want: 50},
		{start: 20, expenses: []int{5, 5, 2}, want: 8},
	}
	for _, testCase := range cases {
		if got := remaining(testCase.start, testCase.expenses); got != testCase.want {
			t.Errorf("remaining(%d, %v) = %d, want %d", testCase.start, testCase.expenses, got, testCase.want)
		}
	}
}
