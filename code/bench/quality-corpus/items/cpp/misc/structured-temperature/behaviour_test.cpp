#include <cstdlib>
#include <iostream>

#include "solution.cpp"

void check(double expected, double actual) {
    if (expected != actual) {
        std::cerr << "expected " << expected << " but got " << actual << '\n';
        std::exit(1);
    }
}

int main() {
    check(32, celsiusToFahrenheit(0));
    check(212, celsiusToFahrenheit(100));
    check(-40, celsiusToFahrenheit(-40));
}
