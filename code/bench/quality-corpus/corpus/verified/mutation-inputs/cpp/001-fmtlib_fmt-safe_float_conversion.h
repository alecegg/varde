FMT_CONSTEXPR auto safe_float_conversion(const From from, int& ec) -> To {
  ec = 0;
  using T = std::numeric_limits<To>;
  static_assert(std::is_floating_point<From>::value, "From must be floating");
  static_assert(std::is_floating_point<To>::value, "To must be floating");

  // catch the only happy case
  if (std::isfinite(from)) {
    if (from >= T::lowest() && from <= (T::max)()) {
      return static_cast<To>(from);
    }
    // not within range.
    ec = 1;
    return {};
  }

  // nan and inf will be preserved
  return static_cast<To>(from);
}  // function
