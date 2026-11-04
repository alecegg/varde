#include <vector>

/** Return the allowance left after the recorded expenses. */
int remainingAllowance(int start, const std::vector<int>& expenses) {
    if (expenses.size() > 1) {
        int left = start;
        for (const int expense : expenses) {
            left -= expense;
        }
        return left;
    }
    int amount = start;
    for (const int expense : expenses) {
        amount -= expense;
    }
    return amount;
}
