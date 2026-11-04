auto operator()(T value) -> unsigned {
  auto width = static_cast<uint32_or_64_or_128_t<T>>(value);
  if (detail::is_negative(value)) {
    specs_.set_align(align::left);
    width = 0 - width;
  }
  unsigned int_max = to_unsigned(max_value<int>());
  if (width > int_max) report_error("number is too big");
  return static_cast<unsigned>(width);
}
