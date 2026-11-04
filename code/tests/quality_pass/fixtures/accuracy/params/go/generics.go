package fixtures

func Identity[T any](value T) T { return value }

func Map[T any, U any](values []T, transform func(T) U) []U { return nil }

func Pair[K comparable, V any](key K, value V) (K, V) { return key, value }

func Zero[T any]() T {
	var zero T
	return zero
}

func Reduce[T any, A any](values []T, initial A, combine func(A, T) A) A {
	return initial
}

func Filtered[T any](values []T, keep func(T) bool, limit int) []T { return nil }
