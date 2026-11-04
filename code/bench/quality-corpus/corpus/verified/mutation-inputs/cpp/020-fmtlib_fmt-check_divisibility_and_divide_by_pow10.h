auto check_divisibility_and_divide_by_pow10(uint32_t& n) noexcept -> bool {
  // The numbers below are chosen such that:
  //   1. floor(n/d) = floor(nm / 2^k) where d=10 or d=100,
  //   2. nm mod 2^k < m if and only if n is divisible by d,
  // where m is magic_number, k is shift_amount
  // and d is divisor.
  //
  // Item 1 is a common technique of replacing division by a constant with
  // multiplication, see e.g. "Division by Invariant Integers Using
  // Multiplication" by Granlund and Montgomery (1994). magic_number (m) is set
  // to ceil(2^k/d) for large enough k.
  // The idea for item 2 originates from Schubfach.
  constexpr auto info = div_small_pow10_infos[N - 1];
  FMT_ASSERT(n <= info.divisor * 10, "n is too large");
  constexpr uint32_t magic_number =
      (1u << info.shift_amount) / info.divisor + 1;
  n *= magic_number;
  const uint32_t comparison_mask = (1u << info.shift_amount) - 1;
  bool result = (n & comparison_mask) < magic_number;
  n >>= info.shift_amount;
  return result;
}
