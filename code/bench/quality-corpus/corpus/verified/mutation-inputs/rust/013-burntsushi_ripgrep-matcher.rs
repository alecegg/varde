pub(crate) fn matcher(&self) -> anyhow::Result<PatternMatcher> {
    match self.engine {
        EngineChoice::Default => match self.matcher_rust() {
            Ok(m) => Ok(m),
            Err(err) => {
                anyhow::bail!(suggest_other_engine(err.to_string()));
            }
        },
        EngineChoice::PCRE2 => Ok(self.matcher_pcre2()?),
        EngineChoice::Auto => {
            let rust_err = match self.matcher_rust() {
                Ok(m) => return Ok(m),
                Err(err) => err,
            };
            log::debug!(
                "error building Rust regex in hybrid mode:\n{rust_err}",
            );

            let pcre_err = match self.matcher_pcre2() {
                Ok(m) => return Ok(m),
                Err(err) => err,
            };
            let divider = "~".repeat(79);
            anyhow::bail!(
                "regex could not be compiled with either the default \
                 regex engine or with PCRE2.\n\n\
                 default regex engine error:\n\
                 {divider}\n\
                 {rust_err}\n\
                 {divider}\n\n\
                 PCRE2 regex engine error:\n{pcre_err}",
            );
        }
    }
}
