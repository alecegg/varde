#include <cstdlib>
#include <iostream>

#include "solution.cpp"

void checkAmount(int gratuity, int total, Amount actual) {
    if (actual.gratuity != gratuity || actual.total != total) {
        std::cerr << "expected " << gratuity << " and " << total << " but got "
                  << actual.gratuity << " and " << actual.total << '\n';
        std::exit(1);
    }
}

int main() {
    checkAmount(2, 22, gratuityFor(20, 10));
    checkAmount(9, 54, gratuityFor(45, 20));
    checkAmount(0, 0, gratuityFor(0, 15));
}
