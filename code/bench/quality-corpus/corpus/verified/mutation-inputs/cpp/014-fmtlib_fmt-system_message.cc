explicit system_message(unsigned long error_code)
    : result_(0), message_(nullptr) {
  result_ = FormatMessageW(
      FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
          FORMAT_MESSAGE_IGNORE_INSERTS,
      nullptr, error_code, MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
      reinterpret_cast<wchar_t*>(&message_), 0, nullptr);
  if (result_ != 0) {
    while (result_ != 0 && is_whitespace(message_[result_ - 1])) {
      --result_;
    }
  }
}
