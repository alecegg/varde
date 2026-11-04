#include <cstdlib>
#include <iostream>
#include <string>

#include "solution.cpp"

void check(const std::string& expected, const std::string& actual) {
    if (expected != actual) {
        std::cerr << "expected '" << expected << "' but got '" << actual << "'\n";
        std::exit(1);
    }
}

int main() {
    check("a b", collapse("a  b"));
    check("hello world", collapse("  hello   world  "));
    check("", collapse(""));
    check("", collapse("   "));
    check("one", collapse("one"));
    check("a b c", collapse("a\tb\nc"));
    check("join these", collapse("join  \t these"));
    check("spaced", collapse(" spaced"));
    check("trailing", collapse("trailing "));
    check("a b c", collapse("a b c"));
    check("x", collapse("x"));
}
