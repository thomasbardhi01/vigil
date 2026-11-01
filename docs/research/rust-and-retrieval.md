# Vigil and Rust: code-retrieval evidence, Rust AI infrastructure, and a Rust target stack (2026-11-01)

Unverified sources per ADR-0006. Produced by an Advanced Research task; the full report with its source list is in the Vigil project (`claude/research/rust-and-retrieval.md`). This file is its `docs/research/` copy. Vendor-reported numbers are marked as such.

## Verdicts against Vigil's positions

- **P1 (vigild stays Python): CONFIRMS.** Every Rust rewrite in agent tooling (Codex CLI: zero-dependency install, Seatbelt/Landlock bindings, no GC; Warp: GPU client) was about a shipped client binary or an inner loop. None applies to an I/O-bound control plane whose latency is LLM calls, Docker and tests. Practitioners who built orchestrators in Rust report a "slowest SDK" tax as agent protocols change on a ~2-month cycle (Scalac); Flyte 2.0 kept Python and moved only hot paths to Rust via PyO3 (Union.ai). Correctness of budgets, FSM and provenance comes from property tests, typed models and replay, not the borrow checker.
- **P2 (code map only if replay shows gains; narrow service): CONFIRMS the gate, EXTENDS the design.** Cleanest causal study ("Code Isn't Memory", arXiv 2606.22417, 91 instances × 3 seeds, Opus 4.7, leak-audited): a structural index (tree-sitter graph + BM25 + vectors) raised localisation acc@5 44.3% → 84.5% and resolve 41.9% → 50.4% (p=0.003) *within one harness*; against agentic-grep OpenCode the gap was 50.4% vs 45.3% (p=0.087, n.s.), cost $2.30 vs $2.92. Independent replication (Dik Rana, 32 tasks, 214 runs, $85, Opus 5): zero tasks discriminated grep from an index; the cost delta flipped sign between repos (−28–54% on a 3.5k-file repo, +15–17% on a 13.5k-file repo). Cursor shipped semantic search (Nov 2025, +12.5% on its internal bench, 6.5–23.5% by model) and removed it in Aug 2026 ("models got very good at grep"); Sourcegraph dropped embeddings for Enterprise; Claude Code and Cline never indexed. LocAgent (ACL 2025): 94.16% file acc@5 and +12% Pass@10; a fine-tuned 32B matched proprietary at ~86% lower cost. RepoGraph (ICLR 2025): +2.0–2.7 pp absolute on SWE-bench Lite. Context rot (Chroma, 18 models): focused ~300-token prompts beat ~113k-token originals across all models; distractors compound. **Surviving designs are structural and lexical, not semantic.**
- **P3 (Vigil builds Rust): CONFIRMS.** Rust's oracle is unusually strong for an outside verifier: rustc, clippy, cargo-nextest JUnit, cargo-deny, sampled cargo-mutants, proptest, miri for `unsafe`. Model Rust skill is benchmark-dependent: 58.14% on SWE-bench Multilingual's Rust slice (Claude 3.7), 5.44–12.13% on Multi-SWE-bench, 28.6% on Rust-SWE-bench (500 tasks; removing the reproduction stage cost OpenHands 42% of solves), 86.0% Rust vs 72.0% Python on Claw-SWE-Bench (GLM 5.1). Compiler-guided repair cut borrow-checker errors 75% (CRUST-bench); RustAssistant fixed 91.46% of individual errors. Qwen3.6-35B-A3B publishes no per-language Rust number.

## Rust vs non-Rust tools (Nov 2026)

Rust: Codex CLI, Warp, uv (8–10× pip cold, 80–115× warm; vendor), ruff (10–100×; vendor), ripgrep (measured), tantivy, Lance/LanceDB, qdrant, candle, mistral.rs, HF tokenizers core, safetensors core. Not Rust: Claude Code (TypeScript), OpenCode (TypeScript on Bun; TUI in Zig), Factory Droid surfaces (TS/Python), llama.cpp (C/C++), vLLM (Python + CUDA). Pattern: Rust wins for shipped binaries, inner loops and native sandbox bindings; Python/TS where logic changes weekly and the SDKs live.

## Rust target stack: verifier signals

| Signal | Tool | Output | Use |
|---|---|---|---|
| Compiles | `cargo check`/`build` | `--message-format=json` | gate 0 |
| Hidden tests | cargo-nextest | JUnit via `[profile.ci.junit]`; retries off | primary verdict |
| Lint | clippy `-D warnings` | JSON | gate; new warnings vs base |
| Supply chain | cargo-deny | licenses, bans, advisories, sources | gate on `Cargo.toml`/`Cargo.lock` changes |
| Test strength | cargo-mutants | `outcomes.json` (never exit codes; timeout outranks missed) | sampled audit |
| Properties | proptest | via nextest | templates for parsers/serialisers |
| UB | miri | nightly, slow | `unsafe` crates only |

Dev image: pinned toolchain + nextest/clippy/deny (~1.5–3 GB inferred); cargo-chef dependency layers per repo commit; sccache on a local-disk volume (no egress); vendored crates; `CARGO_INCREMENTAL=0` in verifier runs. Pitfalls: compile loops (use `cargo check` inner loop, cap turns per error class), repository-structure blindness (trait impls and re-exports are hard to grep — a point for a structural map on Rust repos), reproduction first, feature-flag matrices, cold compiles, `unsafe` as an escape hatch (`#![forbid(unsafe_code)]` in templates).

## Minimum replay eval for a code map (experiment #17)

Tasks: 60–100 replayable from Vigil's merged history (issue → hidden tests from the merged PR), stratified single- vs multi-file and small vs large repo, plus ~30 public anchors; pre-screen by running the control arm k=3 and dropping tasks solved 3/3 or 0/3 by both a cheap and a strong model. Arms: A current packet; B A + ≤1.5k-token structural map pre-injected; C map as a queryable tool only. Both the tower model and one Claude model. k=3 seeds (k=5 on the multi-file stratum if the CI straddles the threshold). Metrics: hidden-test pass rate (primary), $/solved (gateway), input and map tokens, turns-to-first-edit, localisation acc@5, wall time, verifier failure category. Paired McNemar on pass/fail, Wilcoxon on $/task, per stratum. Adopt B or C only if pass rate +≥5 pp at p<0.05, or non-inferior (−1 pp) with ≥15% lower $/solved, no regression on single-file tasks, reproduced on both models or at least the tower.

## Narrow API if adopted

`POST /v1/codemap/query {repo, commit (required; never served for another sha), dirty_paths[], task_text, seed_paths[], views[symbols,callers,tests,churn], budget_tokens (hard cap), max_files}` → `{commit, index_version, cache: hit|incremental|cold, tokens_used, truncated, files[{path, score, why[], symbols[], callers[], tests[], churn_90d}]}`; `GET /v1/codemap/symbol?repo&commit&name` as the agent-tool form. Build: tree-sitter defs/refs/calls, test↔file mapping, 90-day churn; rank BM25 over identifiers/paths/docstrings fused with personalised PageRank from seeds; no embeddings in v1. Freshness: content-addressed by commit, incremental from the nearest cached ancestor via `git diff --name-only`, dirty files overlaid per request and never cached. Budget 1.5k tokens default, 4k max; targets p95 query <500 ms warm, cold build <60 s at 10k files (inferred). Implementation: Python + py-tree-sitter + SQLite FTS5 first; tantivy only if profiled latency fails; qdrant/LanceDB only if a later embeddings arm beats B/C.

## Do not adopt

Rewriting vigild in Rust; an embedding/vector store as code-map v1; a persistent maintained knowledge graph (staleness is the failure mode Claude Code, Cline and Cursor all cite); bulk pre-injection of retrieved code; vendor context engines (need egress/SaaS; rubric-scored vendor gains); replacing llama.cpp with mistral.rs/candle for "Rust-ness"; cargo-mutants or miri as per-task gates; leaderboard Rust numbers for capacity planning.

## Caveats

Vendor-reported: Cursor +12.5%, Augment +71–80% (rubric, one repo), Sourcegraph quality-per-dollar, uv/ruff/tantivy/Lance speedups, Qwen3.6 scores on an internal scaffold; "Code Isn't Memory" authors ship the index they tested; Cursor's removal is sourced to a forum post via one blogger; Roo/Continue retrieval, tree-sitter's language split, Factory's languages, image sizes and all thresholds are inferred. Rust benchmark numbers come from different models and harnesses and cannot be pooled.

Sources (abridged): arXiv 2606.22417; dikrana.dev/blog/code-context-benchmarks-cant-tell; cursor.com/blog/secure-codebase-indexing; sourcegraph.com/docs/cody/faq; aider.chat/2023/10/22/repomap.html; augmentcode.com/blog/context-engine-mcp-now-live; newsletter.pragmaticengineer.com/p/building-claude-code-with-boris-cherny; huggingface.co/papers/2503.09089 (LocAgent); arxiv.org/abs/2410.14684 (RepoGraph); arxiv.org/pdf/2603.01012 (FastCode); github.com/openai/codex discussion #1174 via infoq/heise; scalac.io/blog/multi-agent-ai-rust-orchestrator; union.ai "how we kept Python and got our speed from Rust"; astral.sh/blog/uv; qdrant.tech/blog/why-rust; swebench.com/multilingual; arxiv.org/pdf/2504.02605 (Multi-SWE-bench); dl.acm.org/doi/10.1145/3744916.3773108 (Rust-SWE-bench); arxiv.org/pdf/2606.12344 (Claw-SWE-Bench); qwen.ai/blog?id=qwen3.6-35b-a3b; cs.utexas.edu/~isil/crust-bench.pdf; arxiv 2308.05177 (RustAssistant); github.com/LukeMathWalker/cargo-chef; depot.dev/blog/rust-dockerfile-best-practices; mutants.rs; embarkstudios.github.io/cargo-deny.
