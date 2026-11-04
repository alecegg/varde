fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
    use self::ParseSizeErrorKind::*;

    match self.kind {
        InvalidFormat => write!(
            f,
            "invalid format for size '{}', which should be a non-empty \
             sequence of digits followed by an optional 'K', 'M' or 'G' \
             suffix",
            self.original
        ),
        InvalidInt(ref err) => write!(
            f,
            "invalid integer found in size '{}': {}",
            self.original, err
        ),
        Overflow => write!(f, "size too big in '{}'", self.original),
    }
}
