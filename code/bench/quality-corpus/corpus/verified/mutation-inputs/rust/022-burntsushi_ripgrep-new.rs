pub(crate) fn new(pat: &Glob) -> MatchStrategy {
    if let Some(lit) = pat.basename_literal() {
        MatchStrategy::BasenameLiteral(lit)
    } else if let Some(lit) = pat.literal() {
        MatchStrategy::Literal(lit)
    } else if let Some(ext) = pat.ext() {
        MatchStrategy::Extension(ext)
    } else if let Some(prefix) = pat.prefix() {
        MatchStrategy::Prefix(prefix)
    } else if let Some((suffix, component)) = pat.suffix() {
        MatchStrategy::Suffix { suffix, component }
    } else if let Some(ext) = pat.required_ext() {
        MatchStrategy::RequiredExtension(ext)
    } else {
        MatchStrategy::Regex
    }
}
