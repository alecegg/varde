FMT_CONSTEXPR ansi_color_escape(color_type text_color,
                                const char* esc) noexcept {
  // If we have a terminal color, we need to output another escape code
  // sequence.
  if (text_color.is_terminal_color()) {
    bool is_background = esc == string_view("\x1b[48;2;");
    uint32_t value = text_color.value();
    // Background ASCII codes are the same as the foreground ones but with
    // 10 more.
    if (is_background) value += 10u;

    buffer[size++] = static_cast<Char>('\x1b');
    buffer[size++] = static_cast<Char>('[');

    if (value >= 100u) {
      buffer[size++] = static_cast<Char>('1');
      value %= 100u;
    }
    buffer[size++] = static_cast<Char>('0' + value / 10u);
    buffer[size++] = static_cast<Char>('0' + value % 10u);

    buffer[size++] = static_cast<Char>('m');
    return;
  }

  for (int i = 0; i < 7; i++) {
    buffer[i] = static_cast<Char>(esc[i]);
  }
  rgb color(text_color.value());
  to_esc(color.r, buffer + 7, ';');
  to_esc(color.g, buffer + 11, ';');
  to_esc(color.b, buffer + 15, 'm');
  size = 19;
}
