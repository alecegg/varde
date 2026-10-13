use std::path::Path;
use toz_core::fetch::html_to_markdown;

fn convert(name: &str) -> (String, Option<String>) {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/html")
        .join(name);
    let html = std::fs::read_to_string(path).unwrap();
    html_to_markdown(&html, "https://example.com/post")
}

fn assert_has(md: &str, wanted: &[&str]) {
    for text in wanted {
        assert!(md.contains(text), "missing {text:?} in:\n{md}");
    }
}

fn assert_lacks(md: &str, unwanted: &[&str]) {
    for text in unwanted {
        assert!(!md.contains(text), "unexpected {text:?} in:\n{md}");
    }
}

#[test]
fn article_keeps_the_body_and_drops_the_chrome() {
    let (md, title) = convert("article.html");
    assert_eq!(
        title.as_deref(),
        Some("Understanding Ownership in Rust | Example Blog")
    );
    assert_has(
        &md,
        &[
            "Understanding Ownership",
            "Borrowing in practice",
            "fn longest",
            "Trait objects when you need them",
        ],
    );
    assert_lacks(
        &md,
        &[
            "Accept all cookies",
            "Related posts",
            "Great post",
            "Privacy policy",
            "Sponsored",
            "analytics",
        ],
    );
}

#[test]
fn table_heavy_page_keeps_the_table() {
    let (md, _) = convert("table.html");
    assert_has(
        &md,
        &["| serde", "Serialization framework", "| rayon", "snapshot"],
    );
    assert_lacks(&md, &["Site footer"]);
}

#[test]
fn short_page_uses_the_fallback_without_chrome() {
    let (md, title) = convert("short.html");
    assert_eq!(title.as_deref(), Some("Status"));
    assert_has(&md, &["All systems operational", "No incidents."]);
    assert_lacks(&md, &["Menu", "Contact"]);
}

#[test]
fn odd_markup_still_converts_to_readable_text() {
    let (md, title) = convert("odd.html");
    assert_eq!(title.as_deref(), Some("Notes on café & 日本語"));
    assert_has(
        &md,
        &[
            "First paragraph",
            "日本語のテキスト",
            "item two",
            "café",
            "lait",
        ],
    );
    assert_lacks(&md, &["broken"]);
}
