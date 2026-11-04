#include <string>

#define FIXTURE_LIMIT 8

namespace fixtures {

const char kSeparator = ',';

std::string header() {
    return R"(name,value
alpha,1
)";
}

std::string quote(const std::string& value) {
    std::string result = "'";
    for (char symbol : value) {
        if (symbol == '\\' || symbol == '\'') {
            result += '\\';
        }
        result += symbol;
    }
    result += '\'';
    return result;
}

std::size_t width(const std::string& value) {
    return value.size() > FIXTURE_LIMIT ? FIXTURE_LIMIT : value.size();
}

}  // namespace fixtures
