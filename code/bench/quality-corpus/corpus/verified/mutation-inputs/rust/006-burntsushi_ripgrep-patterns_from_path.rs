pub fn patterns_from_path<P: AsRef<Path>>(path: P) -> io::Result<Vec<String>> {
    let path = path.as_ref();
    let file = std::fs::File::open(path).map_err(|err| {
        io::Error::new(
            io::ErrorKind::Other,
            format!("{}: {}", path.display(), err),
        )
    })?;
    patterns_from_reader(file).map_err(|err| {
        io::Error::new(
            io::ErrorKind::Other,
            format!("{}:{}", path.display(), err),
        )
    })
}
