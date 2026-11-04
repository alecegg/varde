package corpus

import (
	"strings"
	"testing"
)

func TestTokenize(t *testing.T) {
	cases := []struct {
		text string
		want string
	}{
		{text: "Hello, world!", want: "hello|world"},
		{text: "", want: ""},
		{text: "  ", want: ""},
		{text: "one", want: "one"},
		{text: "a,b.c!d?e", want: "a|b|c|d|e"},
		{text: "Mixed CASE Words", want: "mixed|case|words"},
		{text: "trailing   spaces  ", want: "trailing|spaces"},
		{text: "under_score and 9", want: "under_score|and|9"},
		{text: "..,!", want: ""},
		{text: "Hello\tWorld", want: "hello\tworld"},
		{text: "1,2,3", want: "1|2|3"},
	}
	for _, testCase := range cases {
		if got := strings.Join(tokenize(testCase.text), "|"); got != testCase.want {
			t.Errorf("tokenize(%q) = %q, want %q", testCase.text, got, testCase.want)
		}
	}
}

func TestTokenizeWithoutWordsIsNil(t *testing.T) {
	if got := tokenize(""); got != nil {
		t.Errorf("tokenize(%q) = %v, want nil", "", got)
	}
	if got := tokenize("  "); got != nil {
		t.Errorf("tokenize(%q) = %v, want nil", "  ", got)
	}
}
