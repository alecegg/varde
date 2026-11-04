fn as_str(&self) -> &'static str {
    match *self {
        Category::Input => "input",
        Category::Search => "search",
        Category::Filter => "filter",
        Category::Output => "output",
        Category::OutputModes => "output-modes",
        Category::Indexing => "indexing",
        Category::Logging => "logging",
        Category::OtherBehaviors => "other-behaviors",
    }
}
