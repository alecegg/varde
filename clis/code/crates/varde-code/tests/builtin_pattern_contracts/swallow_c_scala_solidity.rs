use super::Case;

/// Fixture contracts for C/Scala/Solidity error-swallowing rules.
///
/// C has no exceptions, so the swallow shapes are a discarded call result
/// (`(void)f();`) and an empty status-check body (`if (<check>) { }`). The cast
/// rule only matches known fallible operations, so a `(void)` cast of a
/// print/format call stays valid; the `if` rule only matches a condition with a
/// comparison, so truthiness and bare-call guards stay valid.
///
/// Scala swallows through an empty (`case _ =>`) or unit (`case _ => ()`) catch
/// body. The two rules do not cross-match, and a `match` arm is out of scope
/// (the pattern is anchored on `try ... catch`).
///
/// Solidity swallows through an empty bare `catch { }` or an empty
/// `catch Error(string memory ...) { }` (named and unnamed parameter forms).
/// `Panic` and `catch (bytes memory ...)` shapes belong to the follow-up audit
/// plan.
///
/// invalid: the swallow shape for the rule. valid: a handler that logs, returns
/// or reverts, a comment-only body, and the other swallow shapes.
pub fn cases() -> Vec<Case> {
    vec![
        Case::new(
            "error-swallow-c-empty-if",
            &["c"],
            vec![
                "void f(void) { if (write(fd, buf, n) == -1) { } }".to_string(),
                "void f(void) { if (close(fd) != 0) {} }".to_string(),
                "void f(void) { if (rc != 0) {\n} }".to_string(),
                "void f(void) { if (index < count) { } }".to_string(),
            ],
            vec![
                "void f(void) { if (write(fd, buf, n) == -1) { log_write_error(); } }".to_string(),
                "void f(void) { if (close(fd) != 0) { return; } }".to_string(),
                "void f(void) { if (rc != 0) { /* intentional */ } }".to_string(),
                "void f(void) { if (ready) { } }".to_string(),
                "void f(void) { if (p->ready) { } }".to_string(),
                "void f(void) { if (available()) { } }".to_string(),
            ],
        ),
        Case::new(
            "error-swallow-c-void-cast",
            &["c"],
            vec![
                "void f(void) { (void)close(fd); }".to_string(),
                "void f(void) { (void)fwrite(buf, 1, n, fp); }".to_string(),
                "void f(void) { (void)sendto(fd, buf, n, 0, addr, len); }".to_string(),
                "void f(void) { (void)fflush(fp); }".to_string(),
                "void f(void) { (void)setsockopt(fd, level, name, value, len); }".to_string(),
            ],
            vec![
                "void f(void) { (void)printf(\"hi\"); }".to_string(),
                "void f(void) { (void)snprintf(buf, n, \"%d\", value); }".to_string(),
                "void f(void) { (void)curl_msnprintf(buf, n, \"hi\"); }".to_string(),
                "void f(void) { (void)rc; }".to_string(),
                "void f(void) { int rc = close(fd); (void)rc; }".to_string(),
                "void f(void) { if (close(fd) != 0) { log_error(); } }".to_string(),
            ],
        ),
        Case::new(
            "error-swallow-scala",
            &["scala"],
            vec![
                "object A { def f(): Unit = { try { work() } catch { case _ => } } }".to_string(),
                "object A { def f(): Unit = {\n  try { work() } catch {\n    case _ =>\n  }\n} }"
                    .to_string(),
            ],
            vec![
                "object A { def f(): Unit = { try { work() } catch { case e: Exception => log(e) } } }"
                    .to_string(),
                "object A { def f(): Unit = { try { work() } catch { case _ => () } } }".to_string(),
                "object A { def f(): Unit = { try { work() } catch { case _ => recover() } } }"
                    .to_string(),
                "object A { def f(): Unit = { try { work() } catch { case _ => /* intentional */ } } }"
                    .to_string(),
            ],
        ),
        Case::new(
            "error-swallow-scala-unit",
            &["scala"],
            vec![
                "object A { def f(): Unit = { try { work() } catch { case _ => () } } }"
                    .to_string(),
            ],
            vec![
                "object A { def f(): Unit = { try { work() } catch { case _: Exception => () } } }"
                    .to_string(),
                "object A { def f(): Unit = { try { work() } catch { case e => () } } }".to_string(),
                "object A { def f(): Unit = { try { work() } catch { case _ => log() } } }"
                    .to_string(),
                "object A { def f(): Unit = { try { work() } catch { case _ => } } }".to_string(),
            ],
        ),
        Case::new(
            "error-swallow-solidity",
            &["solidity"],
            vec![
                "contract C { function f() public { try this.g() { } catch { } } }".to_string(),
                "contract C { function f() public { try this.g() { } catch {} } }".to_string(),
            ],
            vec![
                "contract C { function f() public { try this.g() { } catch { revert(); } } }"
                    .to_string(),
                "contract C { function f() public { try this.g() { } catch { /* intentional */ } } }"
                    .to_string(),
                "contract C { function f() public { try this.g() { } catch Error(string memory reason) { revert(reason); } } }"
                    .to_string(),
                "contract C { function f() public { try this.g() { } catch Panic(uint code) { } } }"
                    .to_string(),
                "contract C { function f() public { try this.g() { } catch (bytes memory data) { } } }"
                    .to_string(),
            ],
        ),
        Case::new(
            "error-swallow-solidity-error",
            &["solidity"],
            vec![
                "contract C { function f() public { try this.g() { } catch Error(string memory reason) { } } }"
                    .to_string(),
                "contract C { function f() public { try this.g() { } catch Error(string memory) { } } }"
                    .to_string(),
            ],
            vec![
                "contract C { function f() public { try this.g() { } catch Error(string memory reason) { revert(reason); } } }"
                    .to_string(),
                "contract C { function f() public { try this.g() { } catch Error(string memory reason) { /* intentional */ } } }"
                    .to_string(),
                "contract C { function f() public { try this.g() { } catch { } } }".to_string(),
                "contract C { function f() public { try this.g() { } catch Panic(uint code) { } } }"
                    .to_string(),
            ],
        ),
    ]
}
