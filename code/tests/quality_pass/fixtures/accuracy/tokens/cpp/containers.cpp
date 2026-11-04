#include <map>
#include <string>
#include <vector>

namespace fixtures {

using Counts = std::map<std::string, int>;

void add(Counts& counts, const std::string& key) {
    counts[key] += 1;
}

std::vector<std::string> top(const Counts& counts, std::size_t limit) {
    std::vector<std::pair<std::string, int>> entries(counts.begin(), counts.end());
    std::sort(entries.begin(), entries.end(), [](const auto& left, const auto& right) {
        return left.second > right.second;
    });
    std::vector<std::string> names;
    for (std::size_t index = 0; index < entries.size() && index < limit; ++index) {
        names.push_back(entries[index].first);
    }
    return names;
}

int total(const Counts& counts) {
    int sum = 0;
    for (const auto& [key, value] : counts) {
        (void)key;
        sum += value;
    }
    return sum;
}

}  // namespace fixtures
