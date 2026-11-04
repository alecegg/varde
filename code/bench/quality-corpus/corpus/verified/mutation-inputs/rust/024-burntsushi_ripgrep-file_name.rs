pub(crate) fn file_name<'a>(path: &Cow<'a, [u8]>) -> Option<Cow<'a, [u8]>> {
    if path.is_empty() {
        return None;
    }
    let last_slash = path.rfind_byte(b'/').map(|i| i + 1).unwrap_or(0);
    let got = match *path {
        Cow::Borrowed(path) => Cow::Borrowed(&path[last_slash..]),
        Cow::Owned(ref path) => Cow::Owned(path[last_slash..].to_vec()),
    };
    if got == &b".."[..] {
        return None;
    }
    Some(got)
}
