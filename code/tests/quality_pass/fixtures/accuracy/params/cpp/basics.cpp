#include <string>
#include <vector>

namespace fixtures {

int zero() {
    return 0;
}

int one(int value) {
    return value;
}

int two(int a, int b) {
    return a + b;
}

int grouped(int a, int b, int c) {
    return a + b + c;
}

int defaulted(int value = 1) {
    return value;
}

int variadic(int value, ...) {
    return value;
}

int no_values(void) {
    return 0;
}

int pointer_value(int* value) {
    return *value;
}

int reference_value(int& value) {
    return value;
}

int callback(int (*fn)(int, int), int value) {
    return fn(value, value);
}

std::string name(const char* first, const std::string& last, bool upper) {
    return last;
}

char initial(const std::string& value, std::size_t index, char fallback) {
    return fallback;
}

}  // namespace fixtures
