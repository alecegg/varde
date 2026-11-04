package corpus

import "strings"

func tokenize(text string) []string {
	return lowered(split(text))
}

func split(text string) []string {
	return pieces(text)
}

func pieces(text string) []string {
	return strings.FieldsFunc(text, space)
}

func space(char rune) bool {
	return blank(char)
}

func blank(char rune) bool {
	return char == ' ' || mark(char)
}

func mark(char rune) bool {
	switch char {
	case ',', '.', '!', '?':
		return true
	default:
		return false
	}
}

func lowered(parts []string) []string {
	if len(parts) == 0 {
		return nil
	}
	result := make([]string, 0, len(parts))
	for _, part := range parts {
		result = append(result, lower(part))
	}
	return result
}

func lower(part string) string {
	return strings.ToLower(part)
}
