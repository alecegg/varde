#include <iomanip>
#include <sstream>
#include <string>

const int kSecondsPerMinute = 60;
const int kMinutesPerHour = 60;
const char kSeparator = ':';
const char kFiller = '0';
const int kWidth = 2;

struct Parts {
    int hours;
    int minutes;
    int seconds;
};

std::string twoDigits(int value) {
    std::ostringstream text;
    text << std::setw(kWidth) << std::setfill(kFiller) << value;
    return text.str();
}

std::string rendered(const Parts& value) {
    std::ostringstream text;
    text << value.hours << kSeparator << twoDigits(value.minutes) << kSeparator
         << twoDigits(value.seconds);
    return text.str();
}

int perHour() {
    return kSecondsPerMinute * kMinutesPerHour;
}

int withinHour(int total) {
    return total % perHour();
}

int remainder(int total) {
    return total % kSecondsPerMinute;
}

int hours(int total) {
    return total / perHour();
}

int minutes(int total) {
    return withinHour(total) / kSecondsPerMinute;
}

Parts parts(int total) {
    return Parts{hours(total), minutes(total), remainder(total)};
}

std::string clock(int seconds) {
    return rendered(parts(seconds));
}
