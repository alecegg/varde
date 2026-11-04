package corpus

import "testing"

func TestFahrenheit(t *testing.T) {
	cases := []struct {
		celsius float64
		want    float64
	}{
		{celsius: 0, want: 32},
		{celsius: 100, want: 212},
		{celsius: -40, want: -40},
	}
	for _, testCase := range cases {
		if got := fahrenheit(testCase.celsius); got != testCase.want {
			t.Errorf("fahrenheit(%v) = %v, want %v", testCase.celsius, got, testCase.want)
		}
	}
}
