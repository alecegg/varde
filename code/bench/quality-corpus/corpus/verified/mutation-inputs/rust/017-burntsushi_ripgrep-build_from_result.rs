pub(crate) fn build_from_result(
    &self,
    result: Result<ignore::DirEntry, ignore::Error>,
) -> Option<Haystack> {
    match result {
        Ok(dent) => self.build(dent),
        Err(err) => {
            err_message!("{err}");
            None
        }
    }
}
