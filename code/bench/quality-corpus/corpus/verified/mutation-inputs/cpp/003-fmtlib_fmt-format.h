constexpr auto format(OutputIt out, const T&... args) const -> OutputIt {
  const V& arg = get_arg_checked<V, N>(args...);
  if constexpr (std::is_convertible<V, basic_string_view<Char>>::value) {
    auto s = basic_string_view<Char>(arg);
    return copy<Char>(s.begin(), s.end(), out);
  } else if constexpr (use_format_as<V>::value) {
    return write<Char>(out, format_as(arg));
  } else if constexpr (use_format_as_member<V>::value) {
    return write<Char>(out, formatter<V>::format_as(arg));
  } else {
    return write<Char>(out, arg);
  }
}
