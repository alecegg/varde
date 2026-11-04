pub(crate) fn build<W: WriteColor>(
    &self,
    matcher: PatternMatcher,
    searcher: grep::searcher::Searcher,
    printer: Printer<W>,
) -> SearchWorker<W> {
    let config = self.config.clone();
    let command_builder = self.command_builder.clone();
    let decomp_builder = config.search_zip.then(|| {
        let mut decomp_builder =
            grep::cli::DecompressionReaderBuilder::new();
        decomp_builder.async_stderr(true);
        decomp_builder
    });
    SearchWorker {
        config,
        command_builder,
        decomp_builder,
        matcher,
        searcher,
        printer,
    }
}
