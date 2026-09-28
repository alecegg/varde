mod file_form;
mod dir_form;
pub mod parent;
#[path = "custom/renamed.rs"]
mod renamed;
mod missing_module;

use serde::Serialize;
use std::fmt;

pub struct Root;

mod inline {
    mod nested_decl;

    #[allow(unused_imports)]
    use super::*;
}
