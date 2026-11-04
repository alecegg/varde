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
    check("0:00:00", clock(0));
    check("0:00:59", clock(59));
    check("0:01:00", clock(60));
    check("0:01:01", clock(61));
    check("0:59:59", clock(3599));
    check("1:00:00", clock(3600));
    check("1:01:01", clock(3661));
    check("1:01:00", clock(3660));
    check("2:00:00", clock(7200));
    check("23:59:59", clock(86399));
    check("100:00:00", clock(360000));
}
