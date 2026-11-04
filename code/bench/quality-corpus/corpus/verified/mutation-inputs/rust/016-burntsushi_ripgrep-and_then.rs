fn and_then<U>(
    self,
    mut then: impl FnMut(T) -> ParseResult<U>,
) -> ParseResult<U> {
    match self {
        ParseResult::Special(mode) => ParseResult::Special(mode),
        ParseResult::Ok(t) => then(t),
        ParseResult::Err(err) => ParseResult::Err(err),
    }
}
