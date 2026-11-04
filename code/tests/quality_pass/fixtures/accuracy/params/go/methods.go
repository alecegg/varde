package fixtures

// Context is a marker type for receiver-only fixtures.
type Context struct{}

// Store exercises receiver exclusion and grouped parameters.
type Store struct {
	items map[string]int
}

func (s *Store) Get(ctx Context, key string) int { return s.items[key] }

func (s *Store) Put(key string, value int) { s.items[key] = value }

func (s *Store) receiverOnly() {}

func (s Store) valueReceiver(delta int) int { return delta }

func (s *Store) grouped(a, b int, c string) int { return a + b }

func NewStore(capacity int) *Store { return &Store{items: make(map[string]int)} }

func OpenStore(path string, readOnly bool, options ...func(*Store)) *Store {
	return &Store{}
}

func (s *Store) merge(other *Store, keys []string) {}

func (s *Store) scale(factor int, offset int, clamp bool) int { return factor }
