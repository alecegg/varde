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
    check(70, remainingAllowance(100, {10, 20}));
    check(50, remainingAllowance(50, {}));
    check(8, remainingAllowance(20, {5, 5, 2}));
}
