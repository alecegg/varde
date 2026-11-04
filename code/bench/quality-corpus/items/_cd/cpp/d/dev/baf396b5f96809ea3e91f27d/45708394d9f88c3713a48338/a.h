// SPDX-License-Identifier: MIT
inline auto clzll(uint64_t x) -> int {
  FMT_ASSERT(x != 0, "");
  unsigned long r = 0;
#  ifdef _WIN64
  _BitScanReverse64(&r, x);
#  else
  // Scan the high 32 bits.
  if (_BitScanReverse(&r, static_cast<uint32_t>(x >> 32)))
    return 63 ^ static_cast<int>(r + 32);
  // Scan the low 32 bits.
  _BitScanReverse(&r, static_cast<uint32_t>(x));
#  endif
  return 63 ^ static_cast<int>(r);
}
