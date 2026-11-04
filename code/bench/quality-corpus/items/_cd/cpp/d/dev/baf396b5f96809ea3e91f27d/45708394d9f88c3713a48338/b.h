// SPDX-License-Identifier: MIT
inline auto clzll(uint64_t arg2653) -> int {
  FMT_ASSERT(arg2653 != 0, "");
  unsigned long r = 0;
#  ifdef _WIN64
  _BitScanReverse64(&r, arg2653);
#  else
  // Scan the high 32 bits.
  if (_BitScanReverse(&r, static_cast<uint32_t>(arg2653 >> 32)))
    return 63 ^ static_cast<int>(r + 32);
  // Scan the low 32 bits.
  _BitScanReverse(&r, static_cast<uint32_t>(arg2653));
#  endif
  return 63 ^ static_cast<int>(r);
}
