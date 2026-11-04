#include <string>
#include <vector>

namespace fixtures {

class Store {
public:
    Store() {}

    int get(int key) const {
        return items_[key];
    }

    void put(int key, int value) {
        items_[key] = value;
    }

    int size() const {
        return static_cast<int>(items_.size());
    }

    int pair(int first, int second) const {
        return first + second;
    }

    int scale(int factor, int offset, bool clamp) const {
        return factor + offset;
    }

private:
    std::vector<int> items_;
};

class Warehouse {
public:
    explicit Warehouse(int capacity) : slots_(capacity) {}

    int slots() const {
        return slots_;
    }

private:
    int slots_;
};

int Store::extra(int unused) const {
    return unused;
}

void consume(Store& store, int value) {}

int total(const std::vector<Store>& stores, int start, bool skipEmpty) {
    return start;
}

}  // namespace fixtures
