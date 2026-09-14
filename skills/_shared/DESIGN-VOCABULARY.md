# Design Vocabulary: Deep Modules

Shared vocabulary for designing deep modules: a lot of behaviour behind a small interface, placed at a clean seam, testable through that interface. Use this language wherever code is being designed or restructured — when agreeing standards (e.g. writing a `/varde-knowledge` standards note in the ARCHITECTURE category), during `/varde-review`'s ARCHITECTURE category, or during `/varde-plan` task decomposition when a task involves a genuinely open interface decision. The aim is leverage for callers, locality for maintainers, and testability for everyone.

## Glossary

Use these terms exactly — don't substitute "component," "service," "API," or "boundary."

- **Module** — anything with an interface and an implementation. Scale-agnostic: a function, class, package, or tier-spanning slice.
- **Interface** — everything a caller must know to use the module correctly: the type signature, plus invariants, ordering constraints, error modes, required configuration, and performance characteristics. Broader than "API" or "signature," which refer only to the type-level surface.
- **Implementation** — what's inside a module. Distinct from **Adapter**: a thing can be a small adapter with a large implementation (a Postgres repo) or a large adapter with a small implementation (an in-memory fake).
- **Depth** — leverage at the interface: the amount of behaviour a caller (or test) can exercise per unit of interface they have to learn. A module is **deep** when a large amount of behaviour sits behind a small interface, **shallow** when the interface is nearly as complex as the implementation.
- **Seam** _(Michael Feathers)_ — a place where you can alter behaviour without editing in that place; the *location* at which a module's interface lives. Where to put the seam is its own design decision, distinct from what goes behind it. Not "boundary" — that's overloaded with DDD's bounded context.
- **Adapter** — a concrete thing that satisfies an interface at a seam. Describes *role* (what slot it fills), not substance (what's inside).
- **Leverage** — what callers get from depth: more capability per unit of interface they learn. One implementation pays back across N call sites and M tests.
- **Locality** — what maintainers get from depth: change, bugs, knowledge, and verification concentrate in one place rather than spreading across callers.

## Deep vs. shallow

**Deep module** = small interface + lots of implementation (complexity hidden). **Shallow module** = large interface + little implementation (mostly pass-through — avoid). When designing an interface, ask: can I reduce the number of methods, simplify the parameters, or hide more complexity inside?

## Principles

- **Depth is a property of the interface, not the implementation.** A deep module can be internally composed of small, mockable, swappable parts — they just aren't part of the interface. A module can have internal seams (private to its implementation, used by its own tests) as well as the external seam at its interface.
- **The deletion test.** Imagine deleting the module. If complexity vanishes, it was a pass-through. If complexity reappears across N callers, it was earning its keep.
- **The interface is the test surface.** Callers and tests cross the same seam. If you want to test *past* the interface, the module is probably the wrong shape.
- **One adapter means a hypothetical seam. Two adapters means a real one.** Don't introduce a seam unless something actually varies across it.

## Designing for testability

- Accept dependencies, don't create them (pass a collaborator in rather than constructing it internally).
- Return results, don't produce side effects, where the operation is naturally a computation.
- Keep the surface area small — fewer methods and simpler params mean fewer, simpler tests.

## Design It Twice

Based on "Design It Twice" (Ousterhout): your first idea is unlikely to be the best. Use this when a task involves a genuinely open interface decision — not a mechanical detail the executor can just work out, but a real fork where multiple shapes are defensible.

1. **Frame the problem space** — write a short explanation of the constraints any new interface would need to satisfy, and a rough illustrative sketch to make them concrete (not a proposal). When the interface extends/implements an existing type and the `varde-code` CLI is available, check its `type_hierarchy` for the existing relationships it must honor.
2. **Spawn 3+ subagents in parallel**, each producing a radically different interface for the same module. Give each a different constraint, e.g.: minimize the interface (1-3 entry points, maximise leverage per entry point); maximise flexibility (support many use cases); optimise for the most common caller (make the default case trivial). Each subagent's brief should include this vocabulary plus any project glossary Concepts, and should independently produce: the interface (types, invariants, error modes), a usage example, what sits behind the seam, and trade-offs.
3. **Present and compare** the designs by depth, locality, and seam placement. Give an opinionated recommendation — the reader wants a strong read, not a menu — and propose a hybrid if elements from different designs combine well.

## Rejected framings

- **Depth as ratio of implementation-lines to interface-lines** (Ousterhout): rewards padding the implementation. Use depth-as-leverage instead.
- **"Interface" as the TypeScript `interface` keyword or a class's public methods**: too narrow — interface here includes every fact a caller must know.
- **"Boundary"**: overloaded with DDD's bounded context. Say **seam** or **interface**.
