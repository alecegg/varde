package corpus

func validIdent(name string) bool {
	if name == "" || !isLetter(name[0]) {
		return false
	}
	for index := 1; index < len(name); index++ {
		if !isLetter(name[index]) && !isDigit(name[index]) && name[index] != '_' {
			return false
		}
	}
	return true
}

func isLetter(char byte) bool {
	return char >= 'a' && char <= 'z' || char >= 'A' && char <= 'Z'
}

func isDigit(char byte) bool {
	return char >= '0' && char <= '9'
}
