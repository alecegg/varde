#include <cctype>
#include <string>

const char kFiller = ' ';

bool blank(char character) {
    return std::isspace(static_cast<unsigned char>(character)) != 0;
}

bool wantsSpace(const std::string& result) {
    return !result.empty() && result.back() != kFiller;
}

std::string withoutLast(const std::string& text) {
    return text.substr(0, text.size() - 1);
}

bool endsWithSpace(const std::string& text) {
    return !text.empty() && text.back() == kFiller;
}

std::string trimmed(const std::string& text) {
    return endsWithSpace(text) ? withoutLast(text) : text;
}

void absorb(std::string& result, char character) {
    if (!blank(character)) {
        result.push_back(character);
        return;
    }
    if (wantsSpace(result)) {
        result.push_back(kFiller);
    }
}

std::string gathered(const std::string& text) {
    std::string result;
    for (char character : text) {
        absorb(result, character);
    }
    return result;
}

std::string collapse(const std::string& text) {
    return trimmed(gathered(text));
}
