#include <vector>

/** Return the balance after applying the signed entries. */
int balance(int opening, const std::vector<int>& entries) {
    int b = opening;
    std::size_t i = 0;
    while (i < entries.size()) {
        const int e = entries[i];
        if (e < 0) {
            if (e == -3) {
                b = b - 3;
            } else {
                b = b + e;
            }
        } else {
            b = b + e;
        }
        i = i + 1;
    }
    return b;
}
