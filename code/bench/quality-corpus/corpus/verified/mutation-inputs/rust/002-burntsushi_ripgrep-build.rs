pub fn build(&self) -> Result<DecompressionMatcher, CommandError> {
    let defaults = if !self.defaults {
        vec![]
    } else {
        default_decompression_commands()
    };
    let mut glob_builder = GlobSetBuilder::new();
    let mut commands = vec![];
    for decomp_cmd in defaults.iter().chain(&self.commands) {
        let glob = Glob::new(&decomp_cmd.glob).map_err(|err| {
            CommandError::io(io::Error::new(io::ErrorKind::Other, err))
        })?;
        glob_builder.add(glob);
        commands.push(decomp_cmd.clone());
    }
    let globs = glob_builder.build().map_err(|err| {
        CommandError::io(io::Error::new(io::ErrorKind::Other, err))
    })?;
    Ok(DecompressionMatcher { globs, commands })
}
