void write_escaped_path(basic_memory_buffer<Char>& quoted,
                        const std::filesystem::path& p,
                        const std::basic_string<PathChar>& native) {
  if constexpr (std::is_same_v<Char, char> &&
                std::is_same_v<PathChar, wchar_t>) {
    auto buf = basic_memory_buffer<wchar_t>();
    write_escaped_string<wchar_t>(std::back_inserter(buf), native);
    bool valid = to_utf8<wchar_t>::convert(quoted, {buf.data(), buf.size()});
    FMT_ASSERT(valid, "invalid utf16");
  } else if constexpr (std::is_same_v<Char, PathChar>) {
    write_escaped_string<std::filesystem::path::value_type>(
        std::back_inserter(quoted), native);
  } else {
    write_escaped_string<Char>(std::back_inserter(quoted), p.string<Char>());
  }
}
