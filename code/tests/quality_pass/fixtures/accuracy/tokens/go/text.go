package fixtures

import (
	"strings"
	"unicode/utf8"
)

const Header = `name,value
alpha,1
`

func SplitNames(raw string) []string {
	parts := strings.Split(raw, ",")
	names := make([]string, 0, len(parts))
	for _, part := range parts {
		trimmed := strings.TrimSpace(part)
		if trimmed != "" {
			names = append(names, trimmed)
		}
	}
	return names
}

func RuneCount(text string) int {
	return utf8.RuneCountInString(text)
}

func Repeat(prefix string, count int) string {
	if count <= 0 {
		return prefix
	}
	return prefix + strings.Repeat(prefix, count-1)
}
