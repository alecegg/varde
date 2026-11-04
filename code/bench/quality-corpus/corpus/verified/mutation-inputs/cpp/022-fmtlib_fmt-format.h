auto format(const T& value, Context& ctx) const -> decltype(ctx.out()) {
  auto buffer = basic_memory_buffer<Char>();
  auto&& formatbuf = detail::formatbuf<std::basic_streambuf<Char>>(buffer);
  auto&& output = std::basic_ostream<Char>(&formatbuf);
  output.imbue(std::locale::classic());  // The default is always unlocalized.
  output << value;
  output.exceptions(std::ios_base::failbit | std::ios_base::badbit);
  return formatter<basic_string_view<Char>, Char>::format(
      {buffer.data(), buffer.size()}, ctx);
}
