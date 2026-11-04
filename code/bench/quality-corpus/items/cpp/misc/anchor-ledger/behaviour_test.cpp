#include <cstdlib>
#include <iostream>

#include "solution.cpp"

void check(int expected, int actual) {
    if (expected != actual) {
        std::cerr << "expected " << expected << " but got " << actual << '\n';
        std::exit(1);
    }
}

int main() {
    check(12, balance(10, {5, -3}));
    check(0, balance(0, {}));
    check(50, balance(100, {-20, -30}));
}
