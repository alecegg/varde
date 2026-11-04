#include <algorithm>
#include <vector>

namespace fixtures {

template <typename T>
T maximum(const std::vector<T>& values) {
    T best = values.front();
    for (const T& value : values) {
        if (value > best) {
            best = value;
        }
    }
    return best;
}

template <typename T, typename Mapper>
auto map_all(const std::vector<T>& values, Mapper mapper) {
    using Result = decltype(mapper(values.front()));
    std::vector<Result> mapped;
    mapped.reserve(values.size());
    for (const T& value : values) {
        mapped.push_back(mapper(value));
    }
    return mapped;
}

int doubled_total(const std::vector<int>& values) {
    auto doubled = map_all(values, [](int value) { return value * 2; });
    int sum = 0;
    for (int value : doubled) {
        sum += value;
    }
    return sum;
}

}  // namespace fixtures
