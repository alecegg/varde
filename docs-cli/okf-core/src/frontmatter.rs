//! Frontmatter parsing and serialization (OKF v0.2 §4).
//!
//! A concept document is a YAML frontmatter block delimited by `---` lines
//! at the top of the file, followed by the markdown body.

use serde_yaml::Value;
use thiserror::Error;

/// Length in bytes of the `\n---` closing delimiter skipped in [`parse`].
const CLOSING_DELIMITER_LEN: usize = "\n---".len();

/// Typed errors for frontmatter parsing — never a panic or silent fallback.
#[derive(Debug, Error)]
pub enum FrontmatterError {
    #[error("concept document must be UTF-8: {0}")]
    NotUtf8(#[from] std::str::Utf8Error),
    #[error("concept document must be delimited by `---` frontmatter markers")]
    MissingDelimiters,
    #[error("frontmatter must be a YAML mapping, got {0}")]
    NotAMapping(&'static str),
    #[error("invalid YAML frontmatter: {0}")]
    InvalidYaml(#[from] serde_yaml::Error),
}

/// Parse a concept document into its frontmatter mapping and markdown body.
///
/// The closing delimiter is the first line consisting of exactly `---`
/// after the opening one; the body is everything after it, trimmed of the
/// newline that follows the closing delimiter. Line-anchored so a `---`
/// occurring inside a YAML block scalar (indented, or with trailing
/// content) is not mistaken for the terminator.
pub fn parse(bytes: &[u8]) -> Result<(Value, String), FrontmatterError> {
    let text = std::str::from_utf8(bytes)?;
    let rest = text
        .strip_prefix("---\n")
        .ok_or(FrontmatterError::MissingDelimiters)?;
    let end = find_closing_delimiter(rest).ok_or(FrontmatterError::MissingDelimiters)?;
    let frontmatter = &rest[..end];
    // An `end` of 0 means the closing `---` is the very first line of
    // `rest`, i.e. an empty frontmatter block (`---\n---\n...`) — there is
    // no frontmatter-content newline preceding it, so only `---` (3 bytes)
    // is skipped rather than the usual `\n---` (4 bytes).
    let delimiter_len = if end == 0 { "---".len() } else { CLOSING_DELIMITER_LEN };
    let body = &rest[end + delimiter_len..];
    let body = body.strip_prefix('\n').unwrap_or(body);

    let frontmatter: Value = if frontmatter.trim().is_empty() {
        Value::Mapping(Default::default())
    } else {
        serde_yaml::from_str(frontmatter)?
    };
    if !frontmatter.is_mapping() {
        return Err(FrontmatterError::NotAMapping(
            "expected a YAML mapping, e.g. `type: decision`",
        ));
    }
    Ok((frontmatter, body.to_string()))
}

/// Find the byte offset (within `rest`, relative to `rest`'s start) marking
/// the end of the frontmatter content, i.e. immediately before the line
/// whose entire content is `---` — never a `---` that merely starts a line
/// inside a YAML block scalar. `0` if that line is `rest`'s very first line
/// (empty frontmatter block).
fn find_closing_delimiter(rest: &str) -> Option<usize> {
    let mut offset: usize = 0;
    for line in rest.split('\n') {
        if line == "---" {
            return Some(offset.saturating_sub(1));
        }
        offset += line.len() + 1;
    }
    None
}

/// Serialize frontmatter and body back into a concept document.
///
/// Round-trips with [`parse`]: `parse(serialize(fm, body))` yields the same
/// frontmatter mapping and body.
pub fn serialize(frontmatter: &Value, body: &str) -> Result<String, FrontmatterError> {
    let yaml = serde_yaml::to_string(frontmatter)?;
    Ok(format!("---\n{yaml}---\n{body}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_frontmatter_and_body() {
        let bytes = b"---\nkey: value\n---\nbody text";
        let (frontmatter, body) = parse(bytes).unwrap();
        assert_eq!(frontmatter["key"], "value");
        assert_eq!(body, "body text");
    }

    #[test]
    fn closing_delimiter_search_ignores_lines_that_only_start_with_dashes() {
        // A line beginning with `---` but not consisting solely of `---`
        // (as could appear inside a YAML block scalar) must not be mistaken
        // for the closing delimiter — only an exact `---` line terminates.
        let rest = "type: decision\n---not-a-delimiter\nmore\n---\nbody";
        assert_eq!(
            find_closing_delimiter(rest),
            Some(rest.find("\n---\nbody").unwrap())
        );
    }

    #[test]
    fn parses_blank_body_lines_after_delimiter() {
        let bytes = b"---\ntype: decision\n---\n\n# Body\n";
        let (frontmatter, body) = parse(bytes).unwrap();
        assert_eq!(frontmatter["type"], "decision");
        assert_eq!(body, "\n# Body\n");
    }

    #[test]
    fn empty_frontmatter_block_parses_as_empty_mapping() {
        // Regression test: `---\n---\n...` (no frontmatter content at all)
        // must be recognized, not rejected as MissingDelimiters.
        let bytes = b"---\n---\nbody";
        let (frontmatter, body) = parse(bytes).unwrap();
        assert!(frontmatter.is_mapping());
        assert_eq!(frontmatter.as_mapping().unwrap().len(), 0);
        assert_eq!(body, "body");
    }

    #[test]
    fn empty_frontmatter_block_with_no_body_parses() {
        let bytes = b"---\n---\n";
        let (frontmatter, body) = parse(bytes).unwrap();
        assert!(frontmatter.is_mapping());
        assert_eq!(body, "");
    }

    #[test]
    fn malformed_without_delimiters_errors() {
        let bytes = b"no frontmatter here";
        let err = parse(bytes).unwrap_err();
        assert!(matches!(err, FrontmatterError::MissingDelimiters));
    }

    #[test]
    fn malformed_without_closing_delimiter_errors() {
        let bytes = b"---\ntype: decision\nbody never delimited";
        assert!(parse(bytes).is_err());
    }

    #[test]
    fn non_mapping_frontmatter_errors() {
        let bytes = b"---\n- just\n- a\n- list\n---\nbody";
        assert!(matches!(
            parse(bytes).unwrap_err(),
            FrontmatterError::NotAMapping(_)
        ));
    }

    #[test]
    fn parse_serialize_round_trip() {
        let bytes = b"---\ntype: decision\ntitle: Test\n---\n# Body\n\nSome text.\n";
        let (frontmatter, body) = parse(bytes).unwrap();
        let out = serialize(&frontmatter, &body).unwrap();
        let (frontmatter2, body2) = parse(out.as_bytes()).unwrap();
        assert_eq!(frontmatter, frontmatter2);
        assert_eq!(body, body2);
    }
}
