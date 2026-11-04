package fixtures

func Map[T any, R any](values []T, mapper func(T) R) []R {
	mapped := make([]R, 0, len(values))
	for _, value := range values {
		mapped = append(mapped, mapper(value))
	}
	return mapped
}

func Filter[T any](values []T, keep func(T) bool) []T {
	result := make([]T, 0, len(values))
	for _, value := range values {
		if keep(value) {
			result = append(result, value)
		}
	}
	return result
}

func Reduce[T any, R any](values []T, seed R, combine func(R, T) R) R {
	running := seed
	for _, value := range values {
		running = combine(running, value)
	}
	return running
}
