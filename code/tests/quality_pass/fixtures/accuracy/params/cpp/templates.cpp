#include <utility>
#include <vector>

namespace fixtures {

template <typename T>
T maximum(const std::vector<T>& values, T fallback) {
    return fallback;
}

template <typename T, typename Mapper>
auto map_all(const std::vector<T>& values, Mapper mapper, int limit) {
    return limit;
}

template <typename... Args>
int count_all(Args... args) {
    return static_cast<int>(sizeof...(args));
}

template <typename T>
struct Box {
    explicit Box(T value) : value_(value) {}

    T get() const {
        return value_;
    }

    void set(T value, bool notify) {
        value_ = value;
    }

    T value_;
};

template <typename T>
std::pair<T, T> both(const T& first, const T& second) {
    return {first, second};
}

}  // namespace fixtures
