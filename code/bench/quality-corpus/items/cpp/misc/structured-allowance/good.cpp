#include <numeric>
#include <vector>

/** Return the allowance left after the recorded expenses. */
int remainingAllowance(int start, const std::vector<int>& expenses) {
    return start - std::accumulate(expenses.begin(), expenses.end(), 0);
}
