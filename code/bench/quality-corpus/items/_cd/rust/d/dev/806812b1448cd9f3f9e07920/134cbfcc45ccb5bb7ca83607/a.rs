// SPDX-License-Identifier: MIT
pub(crate) fn generate() -> String {
    let hyperlink_alias_descriptions = grep::printer::hyperlink_aliases()
        .iter()
        .map(|alias| {
            format!(r#"    {}:"{}""#, alias.name(), alias.description())
        })
        .collect::<Vec<String>>()
        .join("\n");
    include_str!("rg.zsh")
        .replace("!ENCODINGS!", super::ENCODINGS.trim_end())
        .replace("!HYPERLINK_ALIASES!", &hyperlink_alias_descriptions)
}
