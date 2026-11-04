#include <string>
#include <vector>

namespace fixtures {

constexpr int kMaxRetries = 3;
const char* const kDefaultName = "anonymous";

int total(const std::vector<int>& values) {
    int running = 0;
    for (int value : values) {
        running += value;
    }
    return running;
}

std::string render(const std::string& prefix, int index) {
    return prefix + ":" + std::to_string(index);
}

}  // namespace fixtures
