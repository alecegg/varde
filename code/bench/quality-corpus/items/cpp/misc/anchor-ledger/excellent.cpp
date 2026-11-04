#include <numeric>
#include <vector>

int entriesTotal(const std::vector<int>& entries) {
    return std::accumulate(entries.begin(), entries.end(), 0);
}

/** Return the balance after applying the signed entries. */
int balance(int opening, const std::vector<int>& entries) {
    return opening + entriesTotal(entries);
}
