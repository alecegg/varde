//! Pure helpers shared by the Varde modules. Depends on no other `varde-*` crate.

pub mod envelope;
pub mod json_order;
pub mod paths;
pub mod redact;
pub mod skill_relations;
pub mod sqlite;
pub mod text_audit;
#[cfg(feature = "write-meter")]
pub mod write_meter;

/// Start marker of the toz block in a user-owned markdown file.
pub const TOZ_BLOCK_START: &str = "<!-- varde-toz:start -->";
/// End marker of the toz block in a user-owned markdown file.
pub const TOZ_BLOCK_END: &str = "<!-- varde-toz:end -->";

/// Short instruction for recording concrete agent friction and user corrections.
pub const LEARN_NOTE: &str = "Record friction as it happens with `varde learn friction add`. Record each user correction with the user's stated reason. Do not record predicted risks.";

/// The toz usage note injected at session start. Deliberately short.
pub const TOZ_NOTE: &str = "\
varde-toz (tool-output-zone) is active. Large supported tool results are captured by handle. \
For batched or noisy commands, use native code mode on Pi or on Codex with `code_mode` enabled, \
otherwise `varde run run` (the varde-toz skill covers other code modes), and print a filtered summary. Recover details with `varde run query --handle <H>` instead of rerunning; \
read the varde-toz skill when a handle appears.";

/// Render the toz note block from a template holding `{{TOZ_SHARED_NOTE}}`
/// between the toz block markers, for inclusion in Varde's shared instruction block.
///
/// Panics when the template lacks the block markers.
pub fn toz_instruction_block(template: &str) -> String {
    let start = template
        .find(TOZ_BLOCK_START)
        .expect("Toz note block start marker")
        + TOZ_BLOCK_START.len();
    let end = start
        + template[start..]
            .find(TOZ_BLOCK_END)
            .expect("Toz note block end marker");
    template[start..end]
        .trim_matches('\n')
        .replace("{{TOZ_SHARED_NOTE}}", TOZ_NOTE)
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEMPLATE: &str = "head\n<!-- varde-toz:start -->\n## Title\n\n{{TOZ_SHARED_NOTE}}\n<!-- varde-toz:end -->\ntail\n";

    #[test]
    fn block_is_the_text_between_markers_with_the_note_filled_in() {
        assert_eq!(
            toz_instruction_block(TEMPLATE),
            format!("## Title\n\n{TOZ_NOTE}")
        );
    }

    #[test]
    #[should_panic(expected = "start marker")]
    fn missing_marker_panics() {
        toz_instruction_block("no markers");
    }
}
