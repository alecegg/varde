package corpus

import "testing"

func TestGratuity(t *testing.T) {
	cases := []struct {
		bill         int
		percent      int
		wantGratuity int
		wantTotal    int
	}{
		{bill: 20, percent: 10, wantGratuity: 2, wantTotal: 22},
		{bill: 45, percent: 20, wantGratuity: 9, wantTotal: 54},
		{bill: 0, percent: 15, wantGratuity: 0, wantTotal: 0},
	}
	for _, testCase := range cases {
		gotGratuity, gotTotal := gratuity(testCase.bill, testCase.percent)
		if gotGratuity != testCase.wantGratuity || gotTotal != testCase.wantTotal {
			t.Errorf("gratuity(%d, %d) = (%d, %d), want (%d, %d)", testCase.bill, testCase.percent, gotGratuity, gotTotal, testCase.wantGratuity, testCase.wantTotal)
		}
	}
}
