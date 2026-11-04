package corpus

import "strings"

func tokenize(text string) []string {
	var tokens []string
	var current strings.Builder
	for _, char := range text {
		if char == ' ' || char == ',' || char == '.' || char == '!' || char == '?' {
			if current.Len() > 0 {
				tokens = append(tokens, strings.ToLower(current.String()))
				current.Reset()
			}
		} else {
			current.WriteRune(char)
		}
	}
	if current.Len() > 0 {
		tokens = append(tokens, strings.ToLower(current.String()))
	}
	return tokens
}
