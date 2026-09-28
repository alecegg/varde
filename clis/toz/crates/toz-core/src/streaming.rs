//! Bounded ingestion for disk-spooled command output.

use crate::capture::{self, CaptureInput, Outcome, Preview, Section};
use crate::chunk::{self, Chunk};
use crate::metadata;
use crate::redact::{NeverCapture, Redactor};
use crate::store::NewCapture;
use crate::{Config, Store};
use anyhow::{ensure, Result};
use std::io::{BufRead, BufReader, Read, Seek, Write};

/// Smaller captures keep content-aware chunking and whole-document redaction.
pub const STREAM_THRESHOLD: usize = 1024 * 1024;
const MAX_LINE_BYTES: usize = 1024 * 1024;
const BLOCK_BYTES: usize = 256 * 1024;

pub fn run(
    cfg: &Config,
    store: &mut Store,
    mut input: CaptureInput<'_>,
    stdout: &mut (impl Read + Seek),
    stderr: &mut (impl Read + Seek),
    bytes: usize,
) -> Result<Outcome> {
    if !input.force && bytes <= input.threshold.unwrap_or(cfg.threshold) {
        return Ok(Outcome::PassThrough);
    }
    let key = capture::source_key(input.source);
    let sk = input.label.map(str::trim).unwrap_or(&key);
    let never = NeverCapture::from_config(&cfg.capture)?;
    if never.matches(sk) || never.matches(input.source) {
        return Ok(Outcome::Skipped {
            rule: "never-capture",
        });
    }
    if has_binary_sample(stdout, stderr)? {
        return Ok(Outcome::Skipped { rule: "binary" });
    }
    if bytes <= STREAM_THRESHOLD {
        return run_small(cfg, store, &mut input, stdout, stderr);
    }
    run_large(cfg, store, &input, stdout, stderr, bytes, &key, sk)
}

trait ReadSeek: Read + Seek {}
impl<T: Read + Seek> ReadSeek for T {}

fn has_binary_sample(stdout: &mut impl ReadSeek, stderr: &mut impl ReadSeek) -> Result<bool> {
    for reader in [
        &mut *stdout as &mut dyn ReadSeek,
        &mut *stderr as &mut dyn ReadSeek,
    ] {
        reader.rewind()?;
        let mut sample = Vec::new();
        reader.take(8192).read_to_end(&mut sample)?;
        reader.rewind()?;
        if chunk::looks_binary(&sample) {
            return Ok(true);
        }
    }
    Ok(false)
}

fn run_small(
    cfg: &Config,
    store: &mut Store,
    input: &mut CaptureInput<'_>,
    stdout: &mut impl ReadSeek,
    stderr: &mut impl ReadSeek,
) -> Result<Outcome> {
    let mut out = Vec::new();
    let mut err = Vec::new();
    stdout.read_to_end(&mut out)?;
    stderr.read_to_end(&mut err)?;
    // The stream input's metadata is preserved for the normal pipeline.
    capture::run(
        cfg,
        store,
        CaptureInput {
            stdout: &out,
            stderr: &err,
            label: input.label,
            source: input.source,
            kind: input.kind,
            exit_code: input.exit_code,
            session: input.session,
            force: input.force,
            defer_index: input.defer_index,
            threshold: input.threshold,
            file_mtime: input.file_mtime,
            file_hash: input.file_hash.take(),
        },
        // Profile matching for streamed input is out of scope; this caller has no
        // profiles loaded.
        &[],
    )
}

#[allow(clippy::too_many_arguments)]
fn run_large(
    cfg: &Config,
    store: &mut Store,
    input: &CaptureInput<'_>,
    stdout: &mut impl ReadSeek,
    stderr: &mut impl ReadSeek,
    bytes: usize,
    key: &str,
    sk: &str,
) -> Result<Outcome> {
    let redactor = Redactor::from_config(&cfg.redact)?;
    let label = input
        .label
        .map(str::to_string)
        .unwrap_or_else(|| chunk::truncate(key, 120));
    let safe_label = metadata::sanitize_text(&redactor, &label);
    let safe_source = metadata::sanitize_text(&redactor, input.source);
    let private_key = metadata::identity_at(store.path().parent().unwrap(), sk)?;
    let cap = NewCapture {
        label: &safe_label,
        kind: input.kind,
        source: &safe_source,
        source_key: &private_key,
        legacy_source_key: Some(sk),
        bytes,
        exit_code: input.exit_code,
        session: input.session,
        redactions: 0,
        binary: false,
        file_mtime: input.file_mtime,
        file_hash: input.file_hash.as_deref(),
    };
    let mut preview = empty_preview(&safe_label, bytes, input.exit_code);
    let mut stderr_signatures = capture::StderrSignatures::new(cfg.preview_tail);
    preview.handle = store.insert_capture_with(&cap, |append| {
        ingest(
            stdout,
            "stdout",
            cfg,
            &redactor,
            &mut preview,
            &mut stderr_signatures,
            append,
        )?;
        ingest(
            stderr,
            "stderr",
            cfg,
            &redactor,
            &mut preview,
            &mut stderr_signatures,
            append,
        )?;
        Ok(preview.redactions)
    })?;
    preview.stderr_head = stderr_signatures.finish();
    store.log_stats(input.kind, bytes, preview.render().len(), input.session)?;
    Ok(Outcome::Captured(Box::new(preview)))
}

fn empty_preview(label: &str, bytes: usize, exit_code: Option<i32>) -> Preview {
    Preview {
        handle: String::new(),
        label: label.to_string(),
        bytes,
        chunks: 0,
        exit_code,
        redactions: 0,
        binary: false,
        streamed: true,
        sections: Vec::new(),
        sections_omitted: 0,
        head: Vec::new(),
        tail: Vec::new(),
        stderr_lines: 0,
        stderr_head: Vec::new(),
        diagnostics: Vec::new(),
        lines: 0,
        terms: Vec::new(),
        toc: None,
        script_output: None,
    }
}

fn ingest(
    input: impl Read,
    stream: &str,
    cfg: &Config,
    redactor: &Redactor,
    preview: &mut Preview,
    stderr_signatures: &mut capture::StderrSignatures,
    append: &mut dyn FnMut(&str, &Chunk) -> Result<()>,
) -> Result<()> {
    let (sanitized, count) =
        redactor.apply_spooled(|output| normalize_stream(input, output, cfg.redact.builtin))?;
    preview.redactions += count;
    let mut reader = BufReader::new(sanitized);
    let mut line = Vec::new();
    let mut block = String::new();
    let mut block_lines = 0;
    loop {
        line.clear();
        let n = read_stream_line(&mut reader, &mut line)?;
        if n == 0 {
            if !block.is_empty() {
                append_block(&block, stream, cfg, preview, stderr_signatures, append)?;
            }
            break;
        }
        block.push_str(std::str::from_utf8(&line)?);
        block_lines += 1;
        if block_lines >= 80 || block.len() >= BLOCK_BYTES {
            append_block(&block, stream, cfg, preview, stderr_signatures, append)?;
            block.clear();
            block_lines = 0;
        }
    }
    Ok(())
}

fn read_stream_line(reader: &mut impl BufRead, line: &mut Vec<u8>) -> Result<usize> {
    let n = reader
        .take((MAX_LINE_BYTES + 1) as u64)
        .read_until(b'\n', line)?;
    ensure!(
        n <= MAX_LINE_BYTES,
        "streamed capture line exceeds 1 MiB; capture rolled back"
    );
    Ok(n)
}

fn normalize_stream(input: impl Read, output: &mut dyn Write, redact_pem: bool) -> Result<usize> {
    let mut reader = BufReader::new(input);
    let mut line = Vec::new();
    let mut in_pem = false;
    let mut redactions = 0;
    loop {
        line.clear();
        if read_stream_line(&mut reader, &mut line)? == 0 {
            break;
        }
        let text = chunk::strip_ansi(&String::from_utf8_lossy(&line));
        // PEM suppression carries across blocks, including arbitrarily long keys.
        let begin = text.contains("-----BEGIN ") && text.contains("PRIVATE KEY-----");
        let end = text.contains("-----END ") && text.contains("PRIVATE KEY-----");
        if redact_pem && (in_pem || begin) {
            if !in_pem {
                output.write_all(b"[redacted:pem]\n")?;
                redactions += 1;
            }
            in_pem = !end;
        } else {
            output.write_all(text.as_bytes())?;
        }
    }
    Ok(redactions)
}

fn append_block(
    block: &str,
    stream: &str,
    cfg: &Config,
    preview: &mut Preview,
    stderr_signatures: &mut capture::StderrSignatures,
    append: &mut dyn FnMut(&str, &Chunk) -> Result<()>,
) -> Result<()> {
    let text = block;
    let lines: Vec<&str> = text.lines().collect();
    if lines.is_empty() {
        return Ok(());
    }
    let offset = if stream == "stdout" {
        preview.lines
    } else {
        preview.stderr_lines
    };
    let chunk = Chunk {
        ordinal: preview.chunks,
        title: chunk::title_for(&lines),
        line_start: offset + 1,
        line_end: offset + lines.len(),
        content_type: chunk::classify(&lines),
        body: lines.join("\n"),
    };
    append(stream, &chunk)?;
    if preview.sections.len() < cfg.preview_sections {
        preview.sections.push(Section {
            index: preview.chunks,
            index_end: None,
            stream: stream.into(),
            title: chunk.title,
            line_start: chunk.line_start,
            line_end: chunk.line_end,
        });
    } else {
        preview.sections_omitted += 1;
    }
    preview.chunks += 1;
    if stream == "stdout" {
        append_stdout_lines(preview, cfg, text, &lines);
    } else {
        append_stderr_lines(preview, stderr_signatures, &lines);
    }
    Ok(())
}

fn append_stdout_lines(preview: &mut Preview, cfg: &Config, text: &str, lines: &[&str]) {
    if preview.terms.is_empty() {
        preview.terms = crate::terms::distinctive(&[text], 12);
    }
    for line in lines {
        preview.lines += 1;
        capture::push_diagnostic(&mut preview.diagnostics, "stdout", preview.lines, line);
        let line = chunk::truncate(line, 240);
        if preview.head.len() < cfg.preview_head {
            preview.head.push(line);
        } else if cfg.preview_tail > 0 {
            if preview.tail.len() == cfg.preview_tail {
                preview.tail.remove(0);
            }
            preview.tail.push(line);
        }
    }
}

fn append_stderr_lines(
    preview: &mut Preview,
    stderr_signatures: &mut capture::StderrSignatures,
    lines: &[&str],
) {
    for line in lines {
        preview.stderr_lines += 1;
        capture::push_diagnostic(
            &mut preview.diagnostics,
            "stderr",
            preview.stderr_lines,
            line,
        );
        stderr_signatures.push(line);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn large_capture_masks_metadata_before_storage_and_preview() {
        let dir = tempfile::tempdir().unwrap();
        let mut store = Store::open(&dir.path().join("toz.db")).unwrap();
        let mut cfg = Config::default();
        cfg.redact.patterns.push("vault-[0-9]+".into());
        let body = "ordinary output\n".repeat(90_000);
        let mut stdout = Cursor::new(body.as_bytes());
        let mut stderr = Cursor::new(&[][..]);
        let mut input = CaptureInput::new(&[], "task vault-123", "run");
        input.label = Some("label vault-123");
        let Outcome::Captured(preview) = run(
            &cfg,
            &mut store,
            input,
            &mut stdout,
            &mut stderr,
            body.len(),
        )
        .unwrap() else {
            panic!("expected capture");
        };
        let row = store.get_by_handle(&preview.handle).unwrap().unwrap();
        assert!(!row.source.contains("vault-123"));
        assert!(!row.label.contains("vault-123"));
        assert!(!preview.render().contains("vault-123"));
    }

    #[test]
    fn oversized_stderr_line_rolls_back_already_appended_stdout() {
        let dir = tempfile::tempdir().unwrap();
        let database = dir.path().join("toz.db");
        let mut store = Store::open(&database).unwrap();
        let mut stdout = Cursor::new("ordinary output\n".repeat(90_000).into_bytes());
        let mut stderr = Cursor::new(vec![b'x'; MAX_LINE_BYTES + 1]);
        let bytes = stdout.get_ref().len() + stderr.get_ref().len();
        let error = run(
            &Config::default(),
            &mut store,
            CaptureInput::new(&[], "test", "run"),
            &mut stdout,
            &mut stderr,
            bytes,
        )
        .unwrap_err();
        assert!(error
            .to_string()
            .contains("streamed capture line exceeds 1 MiB"));
        let connection = rusqlite::Connection::open(database).unwrap();
        for table in ["captures", "chunks"] {
            let count: i64 = connection
                .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
                    row.get(0)
                })
                .unwrap();
            assert_eq!(count, 0, "partial {table} remained after failure");
        }
    }

    #[test]
    fn user_redaction_crosses_line_and_byte_blocks_in_both_streams() {
        for prefix in [
            "filler\n".repeat(79),
            format!("{}\n", "x".repeat(BLOCK_BYTES - 20)),
        ] {
            let output = format!(
                "{prefix}BEGINPROTECTED\nmy-sensitive-data\nENDPROTECTED\n{}",
                "ordinary output\n".repeat(90_000)
            );
            let dir = tempfile::tempdir().unwrap();
            let mut store = Store::open(&dir.path().join("toz.db")).unwrap();
            let mut cfg = Config::default();
            cfg.redact.patterns = vec!["(?s)BEGINPROTECTED.*?ENDPROTECTED".into()];
            let bytes = output.len() * 2;
            let mut stdout = Cursor::new(output.as_bytes());
            let mut stderr = Cursor::new(output.as_bytes());
            let Outcome::Captured(preview) = run(
                &cfg,
                &mut store,
                CaptureInput::new(&[], "test", "run"),
                &mut stdout,
                &mut stderr,
                bytes,
            )
            .unwrap() else {
                panic!("expected capture");
            };
            let capture = store.get_by_handle(&preview.handle).unwrap().unwrap();
            for stream in ["stdout", "stderr"] {
                let text = store.full_text(capture.id, stream).unwrap();
                assert!(!text.contains("my-sensitive-data"));
                assert!(text.contains("[redacted:user]"));
                assert!(text.contains("ordinary output"));
            }
            assert_eq!(preview.redactions, 2);
            assert!(!preview.render().contains("my-sensitive-data"));
        }
    }

    #[test]
    fn unfinished_pem_stays_suppressed_across_blocks() {
        let dir = tempfile::tempdir().unwrap();
        let mut store = Store::open(&dir.path().join("toz.db")).unwrap();
        let output = format!(
            "{}-----BEGIN PRIVATE KEY-----\n{}",
            "ordinary output\n".repeat(90_000),
            "private-payload\n".repeat(100)
        );
        let bytes = output.len();
        let mut stdout = Cursor::new(output.as_bytes());
        let mut stderr = Cursor::new(Vec::new());
        let Outcome::Captured(preview) = run(
            &Config::default(),
            &mut store,
            CaptureInput::new(&[], "test", "run"),
            &mut stdout,
            &mut stderr,
            bytes,
        )
        .unwrap() else {
            panic!("expected capture");
        };
        let capture = store.get_by_handle(&preview.handle).unwrap().unwrap();
        let text = store.full_text(capture.id, "stdout").unwrap();
        assert!(text.contains("[redacted:pem]"));
        assert!(!text.contains("private-payload"));
        assert_eq!(preview.redactions, 1);
    }

    #[test]
    fn large_stream_preserves_diagnostic_line_numbers() {
        let dir = tempfile::tempdir().unwrap();
        let mut store = Store::open(&dir.path().join("toz.db")).unwrap();
        let mut stdout = Cursor::new(
            format!("{}error: late failure\n", "normal output\n".repeat(90_000)).into_bytes(),
        );
        let mut stderr = Cursor::new(b"notice\nwarning: retrying\n".to_vec());
        let bytes = stdout.get_ref().len() + stderr.get_ref().len();
        let input = CaptureInput::new(&[], "test", "run");
        let Outcome::Captured(preview) = run(
            &Config::default(),
            &mut store,
            input,
            &mut stdout,
            &mut stderr,
            bytes,
        )
        .unwrap() else {
            panic!("expected captured output");
        };
        assert!(preview.streamed);
        assert!(preview
            .render()
            .contains("stdout L90001 [error] error: late failure"));
        assert!(preview
            .render()
            .contains("stderr L2 [warning] warning: retrying"));
    }
}
