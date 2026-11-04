void write_buffer(std::basic_ostream<Char>& os, buffer<Char>& buf,
                  make_unsigned_t<std::streamsize> max_size =
                      to_unsigned(max_value<std::streamsize>())) {
  const Char* buf_data = buf.data();
  using unsigned_streamsize = make_unsigned_t<std::streamsize>;
  unsigned_streamsize size = buf.size();
  do {
    unsigned_streamsize n = size <= max_size ? size : max_size;
    os.write(buf_data, static_cast<std::streamsize>(n));
    buf_data += n;
    size -= n;
  } while (size != 0);
}
