#include <iomanip>
#include <sstream>
#include <string>

std::string clock(int seconds) {
    int hours = seconds / 3600;
    int minutes = (seconds % 3600) / 60;
    int rest = seconds % 60;
    std::ostringstream text;
    text << hours << ':' << std::setw(2) << std::setfill('0') << minutes << ':'
         << std::setw(2) << rest;
    return text.str();
}
