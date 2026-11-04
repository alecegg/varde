package fixtures

import "errors"

var ErrMissing = errors.New("missing key")

type Store struct {
	values map[string]int
}

func NewStore() *Store {
	return &Store{values: make(map[string]int)}
}

func (s *Store) Add(key string, value int) {
	s.values[key] += value
}

func (s *Store) Get(key string) (int, error) {
	value, ok := s.values[key]
	if !ok {
		return 0, ErrMissing
	}
	return value, nil
}

func (s *Store) Sum() int {
	total := 0
	for _, value := range s.values {
		total += value
	}
	return total
}
