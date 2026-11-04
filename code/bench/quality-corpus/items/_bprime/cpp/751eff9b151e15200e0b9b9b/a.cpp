#include <cctype>
#include <string>

std::string collapse(const std::string& text) {
    std::string result;
    for (char character : text) {
        if (std::isspace(static_cast<unsigned char>(character))) {
            if (!result.empty() && result.back() != ' ') {
                result.push_back(' ');
            }
        } else {
            result.push_back(character);
        }
    }
    if (!result.empty() && result.back() == ' ') {
        result.pop_back();
    }
    return result;
}
