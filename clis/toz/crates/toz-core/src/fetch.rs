//! `toz fetch`: HTTP GET → readable text → capture, with a TTL'd disk cache.
//!
//! Cache layout: `<config_dir>/cache/<blake3(url)>.meta` (JSON) + `.body` (the converted text).
//! The body is cached post-conversion so a hit costs one file read. `meta.handle` remembers
//! where the page was stored so a hit can point at the existing capture instead of re-storing.

use crate::capture::{self, CaptureInput, Outcome};
use crate::config::{config_dir, Config};
use crate::redact::Redactor;
use crate::store::Store;
use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::io::Read;
use std::path::PathBuf;
use std::time::Duration;

pub const DEFAULT_TTL_SECS: u64 = 24 * 3600;
const TIMEOUT_SECS: u64 = 30;
const USER_AGENT: &str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 \
                          (KHTML, like Gecko) Chrome/124.0 Safari/537.36 toz/0.1";
/// Bodies larger than this are refused rather than stored.
const MAX_BODY: usize = 20 * 1024 * 1024;

/// CA bundles to fall back on, in order, when `SSL_CERT_FILE` is unset. macOS ships the first;
/// the rest are the usual Linux distribution paths.
const CA_BUNDLES: &[&str] = &[
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/ca-bundle.pem",
];

/// Where to read trust roots from, or `None` to leave it to the platform.
///
/// reqwest's default verifier asks the OS to evaluate each chain, which on macOS means an XPC
/// call to `trustd`. Agent harnesses run their shell under a seatbelt profile that denies that
/// service, so every fetch failed there with an opaque `OSStatus` error even though the peer
/// held an ordinary public certificate. Reading a PEM bundle ourselves keeps verification
/// in-process, so it behaves the same inside a sandbox and out.
fn ca_bundle_path() -> Option<PathBuf> {
    resolve_bundle(std::env::var_os("SSL_CERT_FILE"), CA_BUNDLES)
}

/// The env var wins even when it names a path that does not exist, so that a typo surfaces as an
/// error instead of silently falling through to a system bundle the caller meant to replace.
fn resolve_bundle(env: Option<std::ffi::OsString>, candidates: &[&str]) -> Option<PathBuf> {
    // An empty value counts as unset, matching how every other tool reads SSL_CERT_FILE; a
    // caller that exports it conditionally should not end up with no trust roots at all.
    match env {
        Some(p) if !p.is_empty() => Some(PathBuf::from(p)),
        _ => candidates.iter().map(PathBuf::from).find(|p| p.is_file()),
    }
}

/// Parse `path` as a PEM bundle. An explicit `SSL_CERT_FILE` that cannot be used is an error
/// rather than a silent fallback: the operator asked for that bundle and nothing else.
fn load_roots(path: &std::path::Path) -> Result<Vec<reqwest::Certificate>> {
    let pem =
        std::fs::read(path).with_context(|| format!("reading CA bundle {}", path.display()))?;
    let certs = reqwest::Certificate::from_pem_bundle(&pem)
        .with_context(|| format!("parsing CA bundle {}", path.display()))?;
    if certs.is_empty() {
        bail!("CA bundle {} contains no certificates", path.display());
    }
    Ok(certs)
}

/// What `toz fetch` will verify TLS against, for `toz doctor`. `Ok(None)` means no bundle was
/// found and the platform verifier will be used, which is the path that fails under a sandbox.
pub fn ca_bundle_status() -> Result<Option<(PathBuf, usize)>> {
    match ca_bundle_path() {
        None => Ok(None),
        Some(p) => {
            let n = load_roots(&p)?.len();
            Ok(Some((p, n)))
        }
    }
}

fn http_client() -> Result<reqwest::blocking::Client> {
    let mut b = reqwest::blocking::Client::builder()
        .user_agent(USER_AGENT)
        .timeout(Duration::from_secs(TIMEOUT_SECS))
        .redirect(reqwest::redirect::Policy::limited(10));
    if let Some(path) = ca_bundle_path() {
        let explicit = std::env::var_os("SSL_CERT_FILE").is_some();
        match load_roots(&path) {
            Ok(certs) => b = b.tls_certs_only(certs),
            // A probed path that turns out to be unreadable or malformed is not the operator's
            // doing, so fall back to the platform verifier instead of refusing to fetch.
            Err(e) if !explicit => {
                eprintln!("varde-toz: ignoring CA bundle {}: {e:#}", path.display());
            }
            Err(e) => return Err(e),
        }
    }
    Ok(b.build()?)
}

#[derive(Debug, Clone, Copy)]
pub struct FetchOpts {
    pub ttl_secs: u64,
    pub force: bool,
}

impl Default for FetchOpts {
    fn default() -> Self {
        Self {
            ttl_secs: DEFAULT_TTL_SECS,
            force: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CacheMeta {
    pub url: String,
    pub final_url: String,
    pub content_type: String,
    pub fetched_at: i64,
    pub title: Option<String>,
    pub etag: Option<String>,
    /// Handle the body was stored under, and in which project store.
    pub handle: Option<String>,
    pub project_key: Option<String>,
}

/// A page ready to store: converted text plus provenance.
#[derive(Debug, Clone)]
pub struct Fetched {
    pub meta: CacheMeta,
    pub text: String,
    pub from_cache: bool,
}

pub fn cache_dir() -> Result<PathBuf> {
    Ok(config_dir()?.join("cache"))
}

fn cache_paths(url: &str) -> Result<(PathBuf, PathBuf)> {
    let dir = cache_dir()?;
    let key = blake3::hash(url.as_bytes()).to_hex().to_string();
    Ok((
        dir.join(format!("{key}.meta")),
        dir.join(format!("{key}.body")),
    ))
}

/// URL sans fragment; the supersession key for `fetch` captures.
pub fn normalize_url(url: &str) -> String {
    let u = url.trim();
    match u.find('#') {
        Some(i) => u[..i].to_string(),
        None => u.to_string(),
    }
}

pub fn cache_get(url: &str, ttl_secs: u64) -> Option<Fetched> {
    let (mp, bp) = cache_paths(url).ok()?;
    let meta: CacheMeta = serde_json::from_slice(&std::fs::read(mp).ok()?).ok()?;
    let age = crate::store::now() - meta.fetched_at;
    if age < 0 || age as u64 > ttl_secs {
        return None;
    }
    let text = std::fs::read_to_string(bp).ok()?;
    Some(Fetched {
        meta,
        text,
        from_cache: true,
    })
}

pub fn cache_put(f: &Fetched) -> Result<()> {
    let (mp, bp) = cache_paths(&f.meta.url)?;
    let dir = mp.parent().unwrap();
    std::fs::create_dir_all(dir)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(dir, std::fs::Permissions::from_mode(0o700));
    }
    std::fs::write(&bp, &f.text)?;
    std::fs::write(&mp, serde_json::to_vec(&f.meta)?)?;
    Ok(())
}

/// Delete cache entries older than `max_age_secs`. Returns how many were removed.
pub fn cache_sweep(max_age_secs: i64) -> Result<usize> {
    let dir = cache_dir()?;
    let Ok(rd) = std::fs::read_dir(&dir) else {
        return Ok(0);
    };
    let cutoff = crate::store::now() - max_age_secs;
    let mut n = 0;
    for entry in rd.flatten() {
        let p = entry.path();
        if p.extension().and_then(|e| e.to_str()) != Some("meta") {
            continue;
        }
        let stale = std::fs::read(&p)
            .ok()
            .and_then(|b| serde_json::from_slice::<CacheMeta>(&b).ok())
            .map(|m| m.fetched_at < cutoff)
            .unwrap_or(true);
        if stale {
            let _ = std::fs::remove_file(&p);
            let _ = std::fs::remove_file(p.with_extension("body"));
            n += 1;
        }
    }
    Ok(n)
}

/// Fetch (or load from cache) and convert to text. Does not touch the store, so it is safe
/// to call from worker threads.
pub fn fetch(url: &str, opts: FetchOpts) -> Result<Fetched> {
    let url = normalize_url(url);
    if !opts.force {
        if let Some(hit) = cache_get(&url, opts.ttl_secs) {
            return Ok(hit);
        }
    }
    let client = http_client()?;
    let resp = client
        .get(&url)
        .header(
            "Accept",
            "text/html,application/xhtml+xml,application/json,text/*;q=0.9,*/*;q=0.5",
        )
        .send()
        .with_context(|| format!("GET {url}"))?;
    let status = resp.status();
    if !status.is_success() {
        bail!("GET {url}: HTTP {status}");
    }
    fetched_response(&url, resp)
}

fn fetched_response(url: &str, resp: reqwest::blocking::Response) -> Result<Fetched> {
    let final_url = resp.url().to_string();
    let etag = resp
        .headers()
        .get(reqwest::header::ETAG)
        .and_then(|v| v.to_str().ok())
        .map(str::to_string);
    let content_type = resp
        .headers()
        .get(reqwest::header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("application/octet-stream")
        .to_string();
    if let Some(len) = resp.content_length() {
        if len as usize > MAX_BODY {
            bail!("GET {url}: body is {len} bytes, over the {MAX_BODY} byte limit");
        }
    }
    let mime = content_type
        .split(';')
        .next()
        .unwrap_or("")
        .trim()
        .to_ascii_lowercase();
    if is_binary_mime(&mime) {
        bail!("GET {url}: unsupported content type {mime}");
    }
    let decoded = read_limited_body(url, resp)?;
    let body = String::from_utf8_lossy(&decoded);
    let (text, title) = to_text(&mime, &body, &final_url);
    Ok(Fetched {
        meta: CacheMeta {
            url: url.to_string(),
            final_url,
            content_type,
            fetched_at: crate::store::now(),
            title,
            etag,
            handle: None,
            project_key: None,
        },
        text,
        from_cache: false,
    })
}

fn read_limited_body(url: &str, resp: reqwest::blocking::Response) -> Result<Vec<u8>> {
    // Response implements `Read` over reqwest's decoded stream. Bound that stream rather
    // than calling `text()`, which would buffer the entire decompressed body first.
    let mut decoded = Vec::with_capacity(MAX_BODY.min(64 * 1024));
    resp.take((MAX_BODY + 1) as u64)
        .read_to_end(&mut decoded)
        .with_context(|| format!("reading body of {url}"))?;
    if decoded.len() > MAX_BODY {
        bail!(
            "GET {url}: body is {} bytes, over the {MAX_BODY} byte limit",
            decoded.len()
        );
    }
    Ok(decoded)
}

fn is_binary_mime(mime: &str) -> bool {
    mime.starts_with("image/")
        || mime.starts_with("audio/")
        || mime.starts_with("video/")
        || mime.starts_with("font/")
        || matches!(
            mime,
            "application/octet-stream"
                | "application/pdf"
                | "application/zip"
                | "application/gzip"
                | "application/x-tar"
                | "application/wasm"
        )
}

/// Route by MIME type: HTML → readability → markdown; JSON → pretty; anything else as-is.
pub fn to_text(mime: &str, body: &str, url: &str) -> (String, Option<String>) {
    match mime {
        "text/html" | "application/xhtml+xml" => html_to_markdown(body, url),
        "application/json" | "text/json" => match serde_json::from_str::<serde_json::Value>(body) {
            Ok(v) => (
                serde_json::to_string_pretty(&v).unwrap_or_else(|_| body.to_string()),
                None,
            ),
            Err(_) => (body.to_string(), None),
        },
        m if m.ends_with("+json") => match serde_json::from_str::<serde_json::Value>(body) {
            Ok(v) => (
                serde_json::to_string_pretty(&v).unwrap_or_else(|_| body.to_string()),
                None,
            ),
            Err(_) => (body.to_string(), None),
        },
        _ => {
            // Servers sometimes mislabel HTML as text/plain.
            let head = body.trim_start().get(..256).unwrap_or(body.trim_start());
            let lower = head.to_ascii_lowercase();
            if lower.starts_with("<!doctype html") || lower.starts_with("<html") {
                html_to_markdown(body, url)
            } else {
                (body.to_string(), None)
            }
        }
    }
}

/// Readability extraction then markdown. Falls back to converting the whole document (minus
/// obvious chrome) when extraction fails or yields almost nothing.
pub fn html_to_markdown(html: &str, url: &str) -> (String, Option<String>) {
    let converter = htmd::HtmlToMarkdown::builder()
        .skip_tags(vec!["script", "style", "noscript", "svg", "iframe"])
        .build();
    let article = dom_smoothie::Readability::new(html, Some(url), None)
        .ok()
        .and_then(|mut r| r.parse().ok());
    if let Some(a) = article {
        if let Ok(md) = converter.convert(&a.content) {
            let md = tidy(&md);
            if md.len() >= 200 {
                let title = non_empty(&a.title);
                let out = match &title {
                    Some(t) => format!("# {t}\n\n{md}\n"),
                    None => format!("{md}\n"),
                };
                return (out, title);
            }
        }
    }
    let fallback = htmd::HtmlToMarkdown::builder()
        .skip_tags(vec![
            "script", "style", "noscript", "svg", "iframe", "nav", "header", "footer", "aside",
        ])
        .build();
    let md = fallback
        .convert(html)
        .map(|m| tidy(&m))
        .unwrap_or_else(|_| html.to_string());
    let title = extract_title(html);
    (format!("{md}\n"), title)
}

fn non_empty(s: &str) -> Option<String> {
    let t = s.trim();
    (!t.is_empty()).then(|| t.to_string())
}

fn extract_title(html: &str) -> Option<String> {
    let lower = html.to_ascii_lowercase();
    let start = lower.find("<title")?;
    let start = start + lower[start..].find('>')? + 1;
    let end = start + lower[start..].find("</title>")?;
    non_empty(
        &html[start..end]
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" "),
    )
}

/// Collapse runs of blank lines and trim trailing whitespace on each line.
fn tidy(md: &str) -> String {
    let mut out = String::with_capacity(md.len());
    let mut blank = 0;
    for line in md.lines() {
        let l = line.trim_end();
        if l.is_empty() {
            blank += 1;
            if blank > 1 {
                continue;
            }
        } else {
            blank = 0;
        }
        out.push_str(l);
        out.push('\n');
    }
    out.trim().to_string()
}

/// Store a fetched page and update the cache so the next hit can point at this handle.
pub fn store_fetched(
    cfg: &Config,
    store: &mut Store,
    project_key: &str,
    f: &mut Fetched,
    label: Option<&str>,
    session: Option<&str>,
) -> Result<Outcome> {
    let source = f.meta.url.clone();
    let mut input = CaptureInput::new(f.text.as_bytes(), &source, "fetch");
    input.label = label;
    input.session = session;
    input.force = true;
    let outcome = capture::run(cfg, store, input, &[])?;
    if let Outcome::Captured(p) = &outcome {
        f.meta.handle = Some(p.handle.clone());
        f.meta.project_key = Some(project_key.to_string());
        let text = crate::chunk::strip_ansi(&f.text);
        let (text, _) = Redactor::from_config(&cfg.redact)?.apply(&text);
        let cached = Fetched { text, ..f.clone() };
        cache_put(&cached)?;
    }
    Ok(outcome)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader, Write};
    use std::sync::Mutex;

    static CONFIG_ENV: Mutex<()> = Mutex::new(());

    const CA_ROOT_PEM: &str = include_str!("../tests/fixtures/ca-root.pem");

    fn tmp_pem(name: &str, body: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!("toz-ca-{name}-{}.pem", std::process::id()));
        std::fs::write(&p, body).unwrap();
        p
    }

    #[test]
    fn an_explicit_bundle_wins_over_the_probed_ones() {
        let probed = tmp_pem("probed", CA_ROOT_PEM);
        let chosen = resolve_bundle(Some("/from/env.pem".into()), &[probed.to_str().unwrap()]);
        assert_eq!(chosen, Some(PathBuf::from("/from/env.pem")));
        let _ = std::fs::remove_file(probed);
    }

    #[test]
    fn a_missing_explicit_bundle_is_still_chosen_so_the_typo_surfaces() {
        // The alternative — falling through to a system bundle — would quietly ignore the
        // operator's choice and connect with roots they did not ask for.
        let real = tmp_pem("fallthrough", CA_ROOT_PEM);
        let chosen = resolve_bundle(
            Some("/definitely/not/here.pem".into()),
            &[real.to_str().unwrap()],
        );
        assert_eq!(chosen, Some(PathBuf::from("/definitely/not/here.pem")));
        assert!(load_roots(&chosen.unwrap()).is_err());
        let _ = std::fs::remove_file(real);
    }

    #[test]
    fn an_empty_env_var_counts_as_unset() {
        let real = tmp_pem("empty-env", CA_ROOT_PEM);
        let chosen = resolve_bundle(Some("".into()), &[real.to_str().unwrap()]);
        assert_eq!(chosen, Some(real.clone()));
        let _ = std::fs::remove_file(real);
    }

    #[test]
    fn probing_skips_paths_that_do_not_exist_and_takes_the_first_that_does() {
        let real = tmp_pem("probe-order", CA_ROOT_PEM);
        let chosen = resolve_bundle(None, &["/nope/a.pem", real.to_str().unwrap()]);
        assert_eq!(chosen, Some(real.clone()));
        assert_eq!(resolve_bundle(None, &["/nope/a.pem"]), None);
        let _ = std::fs::remove_file(real);
    }

    #[test]
    fn a_pem_bundle_loads_and_junk_is_rejected() {
        let good = tmp_pem("good", CA_ROOT_PEM);
        assert_eq!(load_roots(&good).unwrap().len(), 1);
        let _ = std::fs::remove_file(good);

        // An empty or comment-only file parses as zero certificates. Accepting it would build a
        // client that trusts nothing and fails every fetch with an opaque UnknownIssuer.
        let empty = tmp_pem("empty", "# no certificates here\n");
        let err = load_roots(&empty).unwrap_err().to_string();
        assert!(err.contains("no certificates"), "{err}");
        let _ = std::fs::remove_file(empty);
    }

    #[test]
    fn a_bundle_of_two_certs_yields_two_roots() {
        let two = tmp_pem("two", &format!("{CA_ROOT_PEM}{CA_ROOT_PEM}"));
        assert_eq!(load_roots(&two).unwrap().len(), 2);
        let _ = std::fs::remove_file(two);
    }

    const PAGE: &str = r#"<!doctype html><html><head><title>Widget Docs</title>
<style>body{}</style><script>var x=1;</script></head>
<body><nav><a href="/">Home</a><a href="/about">About</a></nav>
<main><article><h1>Widget Docs</h1>
<p>The widget crate provides a <code>Widget</code> type that can be configured with a builder.
This paragraph exists to give the readability heuristics enough content to consider the article
real, because very short pages are treated as boilerplate and dropped entirely.</p>
<h2>Install</h2><pre><code>cargo add widget</code></pre>
<p>Then call <code>Widget::builder()</code> and set the options you need. Every option has a
sensible default so the minimal program is just a few lines long and reads clearly.</p>
</article></main>
<footer>Copyright 2026 Widget Corp. All rights reserved. Terms. Privacy.</footer>
</body></html>"#;

    fn serve_repeated(
        extra_headers: &str,
        chunk: Vec<u8>,
        repeats: usize,
        chunked: bool,
    ) -> String {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        let extra_headers = extra_headers.to_string();
        std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            loop {
                let mut line = String::new();
                reader.read_line(&mut line).unwrap();
                if line.trim().is_empty() {
                    break;
                }
            }
            let size_header = if chunked {
                "Transfer-Encoding: chunked\r\n".to_string()
            } else {
                format!("Content-Length: {}\r\n", chunk.len() * repeats)
            };
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n{extra_headers}{size_header}Connection: close\r\n\r\n"
            )
            .unwrap();
            for _ in 0..repeats {
                let result = if chunked {
                    write!(stream, "{:x}\r\n", chunk.len())
                        .and_then(|_| stream.write_all(&chunk))
                        .and_then(|_| stream.write_all(b"\r\n"))
                } else {
                    stream.write_all(&chunk)
                };
                if result.is_err() {
                    return;
                }
            }
            if chunked {
                let _ = stream.write_all(b"0\r\n\r\n");
            }
        });
        format!("http://{addr}/body")
    }

    fn append_bits(bits: &mut Vec<bool>, value: u16, width: u8) {
        for shift in 0..width {
            bits.push(value & (1 << shift) != 0);
        }
    }

    fn append_fixed_code(bits: &mut Vec<bool>, canonical: u16, width: u8) {
        append_bits(bits, canonical.reverse_bits() >> (16 - width), width);
    }

    fn gzip_bomb() -> Vec<u8> {
        let repeats = MAX_BODY / 258 + 1;
        let decoded_len = 1 + repeats * 258;
        assert_eq!(decoded_len, 20_971_531);

        let mut bits = Vec::with_capacity(repeats * 13 + 32);
        append_bits(&mut bits, 1, 1); // final block
        append_bits(&mut bits, 1, 2); // fixed Huffman block
        append_fixed_code(&mut bits, 48 + u16::from(b'a'), 8);
        for _ in 0..repeats {
            append_fixed_code(&mut bits, 197, 8); // symbol 285: length 258
            append_fixed_code(&mut bits, 0, 5); // distance 1
        }
        append_fixed_code(&mut bits, 0, 7); // end-of-block symbol 256

        let mut body = vec![0x1f, 0x8b, 0x08, 0, 0, 0, 0, 0, 0, 0xff];
        body.extend(bits.chunks(8).map(|chunk| {
            chunk
                .iter()
                .enumerate()
                .fold(0u8, |byte, (shift, bit)| byte | (u8::from(*bit) << shift))
        }));
        body.extend(0x9709ba50u32.to_le_bytes()); // CRC32 for decoded `a` bytes
        body.extend((decoded_len as u32).to_le_bytes());
        body
    }

    #[test]
    fn fetch_rejects_chunked_body_over_decoded_limit() {
        let url = serve_repeated("", vec![b'x'; 1024], MAX_BODY / 1024 + 1, true);
        let err = fetch(
            &url,
            FetchOpts {
                force: true,
                ..FetchOpts::default()
            },
        )
        .unwrap_err();
        assert!(
            format!("{err:#}").contains("over the 20971520 byte limit"),
            "{err:#}"
        );
    }

    #[test]
    fn fetch_rejects_compressed_body_over_decoded_limit() {
        // The fixed-Huffman stream expands to just over 20 MiB of `a` bytes.
        let member = gzip_bomb();
        let url = serve_repeated("Content-Encoding: gzip\r\n", member, 1, false);
        let err = fetch(
            &url,
            FetchOpts {
                force: true,
                ..FetchOpts::default()
            },
        )
        .unwrap_err();
        assert!(
            format!("{err:#}").contains("over the 20971520 byte limit"),
            "{err:#}"
        );
    }

    #[test]
    fn html_becomes_markdown_without_chrome() {
        let (md, title) = html_to_markdown(PAGE, "https://example.com/docs");
        assert_eq!(title.as_deref(), Some("Widget Docs"));
        assert!(md.starts_with("# Widget Docs"), "{md}");
        assert!(md.contains("## Install"), "{md}");
        assert!(md.contains("cargo add widget"), "{md}");
        assert!(!md.contains("var x=1"), "{md}");
        assert!(!md.contains("Privacy"), "{md}");
    }

    #[test]
    fn json_is_pretty_printed_and_text_untouched() {
        let (j, _) = to_text("application/json", r#"{"a":[1,2],"b":{"c":true}}"#, "u");
        assert!(j.contains("\"a\": [\n"), "{j}");
        let (t, _) = to_text("text/plain", "plain  text\n", "u");
        assert_eq!(t, "plain  text\n");
        let (h, _) = to_text("text/plain", PAGE, "u");
        assert!(h.contains("## Install"));
    }

    #[test]
    fn normalize_strips_fragment() {
        assert_eq!(normalize_url(" https://a/b#frag "), "https://a/b");
        assert_eq!(normalize_url("https://a/b?q=1"), "https://a/b?q=1");
    }

    #[test]
    fn cache_roundtrip_and_ttl() {
        let _env_guard = CONFIG_ENV
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let dir = tempfile::tempdir().unwrap();
        std::env::set_var("TOZ_CONFIG_DIR", dir.path());
        let f = Fetched {
            meta: CacheMeta {
                url: "https://x/y".into(),
                final_url: "https://x/y".into(),
                content_type: "text/plain".into(),
                fetched_at: crate::store::now() - 100,
                title: None,
                etag: None,
                handle: Some("abcd".into()),
                project_key: None,
            },
            text: "body".into(),
            from_cache: false,
        };
        cache_put(&f).unwrap();
        let hit = cache_get("https://x/y", 3600).unwrap();
        assert!(hit.from_cache);
        assert_eq!(hit.text, "body");
        assert_eq!(hit.meta.handle.as_deref(), Some("abcd"));
        assert!(cache_get("https://x/y", 50).is_none());
        assert_eq!(cache_sweep(50).unwrap(), 1);
        assert!(cache_get("https://x/y", 3600).is_none());
        std::env::remove_var("TOZ_CONFIG_DIR");
    }

    #[test]
    fn stored_fetch_cache_contains_only_redacted_text() {
        let _env_guard = CONFIG_ENV
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let dir = tempfile::tempdir().unwrap();
        std::env::set_var("TOZ_CONFIG_DIR", dir.path());
        let mut cfg = Config::default();
        cfg.redact.patterns.push(r"internal-[0-9]+".into());
        let mut store = Store::open(&dir.path().join("store.db")).unwrap();
        let secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789";
        let original = format!("credential \x1b[31m{secret}\x1b[0m\nreference=internal-4217\n");
        let mut fetched = Fetched {
            meta: CacheMeta {
                url: "https://example.com/docs".into(),
                final_url: "https://example.com/docs".into(),
                content_type: "text/plain".into(),
                fetched_at: crate::store::now(),
                title: None,
                etag: None,
                handle: None,
                project_key: None,
            },
            text: original.clone(),
            from_cache: false,
        };

        let outcome = store_fetched(&cfg, &mut store, "project", &mut fetched, None, None).unwrap();
        let Outcome::Captured(preview) = outcome else {
            panic!("fetch should always be captured");
        };
        assert_eq!(preview.redactions, 2);
        assert_eq!(fetched.text, original);

        let cached = cache_get(&fetched.meta.url, 60).unwrap();
        assert!(!cached.text.contains(secret));
        assert!(!cached.text.contains("internal-4217"));
        assert!(!cached.text.contains('\x1b'));
        assert!(cached.text.contains("[redacted:github]"));
        assert!(cached.text.contains("[redacted:user]"));

        let row = store.get_by_handle(&preview.handle).unwrap().unwrap();
        assert_eq!(row.redactions, 2);
        std::env::remove_var("TOZ_CONFIG_DIR");
    }
}
