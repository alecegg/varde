inline auto is_big_endian() -> bool {
#ifdef _WIN32
  return false;
#elif defined(__BIG_ENDIAN__)
  return true;
#elif defined(__BYTE_ORDER__) && defined(__ORDER_BIG_ENDIAN__)
  return __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__;
#else
  struct bytes {
    char data[sizeof(int)];
  };
  return bit_cast<bytes>(1).data[0] == 0;
#endif
}
