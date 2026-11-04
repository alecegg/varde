pub(crate) fn update(&mut self, new: Mode) {
    match *self {
        // If we're in a search mode, then anything can override it.
        Mode::Search(_) => *self = new,
        _ => {
            // Once we're in a non-search mode, other non-search modes
            // can override it. But search modes cannot. So for example,
            // `--files -l` will still be Mode::Files.
            if !matches!(*self, Mode::Search(_)) {
                *self = new;
            }
        }
    }
}
