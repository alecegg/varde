//! Learn-side adapter for shared text redaction.

/// Redacted text and the number of replacements made.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Redacted {
    pub text: String,
    pub count: usize,
}

/// Redact built-in secret patterns from text.
pub fn apply(text: &str) -> Redacted {
    let redactor = varde_core::redact::Redactor::new(&Default::default())
        .expect("default redaction configuration is valid");
    let result = redactor.redact(text);
    let count = result.notices.iter().map(|notice| notice.count).sum();
    Redacted {
        text: result.text,
        count,
    }
}

#[cfg(test)]
mod tests {
    use super::apply;

    #[test]
    fn redacts_engine_sample_secrets_and_counts_replacements() {
        let result = apply("keys: AKIAIOSFODNN7EXAMPLE and xoxb-1234567890");

        assert_eq!(
            result.text,
            "keys: [redacted:aws-key] and [redacted:slack]"
        );
        assert_eq!(result.count, 2);
    }

    #[test]
    fn leaves_text_without_secrets_unchanged() {
        let result = apply("ordinary text");

        assert_eq!(result.text, "ordinary text");
        assert_eq!(result.count, 0);
    }
}
