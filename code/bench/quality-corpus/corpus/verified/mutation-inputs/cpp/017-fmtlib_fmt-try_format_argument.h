constexpr static auto try_format_argument(
    OutputIt& out,
    // [[maybe_unused]] due to unused-but-set-parameter warning in GCC 7,8,9
    [[maybe_unused]] basic_string_view<Char> arg_name, const T& arg) -> bool {
  if constexpr (is_named_arg<typename std::remove_cv<T>::type>::value) {
    if (arg_name == arg.name) {
      out = write<Char>(out, arg.value);
      return true;
    }
  }
  return false;
}
