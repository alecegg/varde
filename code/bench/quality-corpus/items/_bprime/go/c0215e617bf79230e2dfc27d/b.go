package corpus

func validIdent(name string) bool {
	return accepted(bytes(name))
}

func bytes(name string) []byte {
	return []byte(name)
}

func accepted(chars []byte) bool {
	if empty(chars) {
		return false
	}
	return opening(chars[0]) && rest(chars[1:])
}

func empty(chars []byte) bool {
	return len(chars) == 0
}

func opening(char byte) bool {
	return letter(char)
}

func rest(chars []byte) bool {
	for _, char := range chars {
		if !allowed(char) {
			return false
		}
	}
	return true
}

func allowed(char byte) bool {
	return letter(char) || digit(char) || underscore(char)
}

func underscore(char byte) bool {
	return char == '_'
}

func letter(char byte) bool {
	return char >= 'a' && char <= 'z' || char >= 'A' && char <= 'Z'
}

func digit(char byte) bool {
	return char >= '0' && char <= '9'
}
