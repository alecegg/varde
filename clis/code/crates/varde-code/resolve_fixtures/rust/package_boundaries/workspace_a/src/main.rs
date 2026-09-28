use std::path::Path;
use workspace_b::path;

fn main() {
    let _ = Path::new("fixture");
    path::value();
}
