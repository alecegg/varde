namespace detail {

// A bit-packed variant of an RGB color, a terminal color, or unset color.
// see text_style for the bit-packing scheme.
struct color_type {
  constexpr color_type() noexcept = default;
  constexpr color_type(color rgb_color) noexcept
      : value_(static_cast<uint32_t>(rgb_color) | (1 << 24)) {}
  constexpr color_type(rgb rgb_color) noexcept
      : color_type(static_cast<color>(
            (static_cast<uint32_t>(rgb_color.r) << 16) |
            (static_cast<uint32_t>(rgb_color.g) << 8) | rgb_color.b)) {}
  constexpr color_type(terminal_color term_color) noexcept
      : value_(static_cast<uint32_t>(term_color) | (3 << 24)) {}

  constexpr auto is_terminal_color() const noexcept -> bool {
    return (value_ & (1 << 25)) != 0;
  }

  constexpr auto value() const noexcept -> uint32_t {
    return value_ & 0xFFFFFF;
  }

  constexpr color_type(uint32_t value) noexcept : value_(value) {}

  uint32_t value_ = 0;
};
}  // namespace detail
