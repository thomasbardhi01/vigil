# syntax=docker/dockerfile:1
# Claude executor (coord, worker, reviewer, auditor sessions). linux/arm64.
#
# Build with scripts/build-images.py, which passes claude-mods at the pinned
# SHA as a build context (a `git archive` of vigild's mirror), so no token is
# needed at build time and nothing is cloned at run time (B16).
#
# Pins: CPython 3.14.8, Node 24.21.0 (only to run the CLI), Claude Code CLI
# 2.1.306 (owner exception to the two-week rule, Q1), claude-agent-sdk 0.2.165.
# Base images are pinned by digest (docs/sources.md).

FROM node:24.21.0-trixie-slim@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66 AS node

FROM python:3.14.8-slim-trixie@sha256:fbecd461fc72d21b2143c6eaba25143738079154a6d0ea3da3aec724f50eed4a

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates ripgrep \
 && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
# The CLI and its whole dependency tree come from a committed lockfile
# (generated with --before=2026-10-22, the day after 2.1.306 shipped).
COPY cli/package.json cli/package-lock.json /opt/claude-cli/
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && cd /opt/claude-cli && npm ci --no-fund --no-audit \
 && ln -s /opt/claude-cli/node_modules/.bin/claude /usr/local/bin/claude \
 && npm cache clean --force \
 && claude --version | grep -q '^2\.1\.306'

# The SDK and its transitive deps, hash-locked (uv pip compile --generate-hashes,
# exclude-newer 2026-10-08): images/claude-executor/requirements.txt.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt

# The agent uid (bypassPermissions refuses root).
RUN groupadd -g 10001 vigil && useradd -u 10001 -g 10001 -m -d /home/vigil -s /bin/bash vigil

# guard@claude-mods, seeded at build time from the pinned SHA (B16).
COPY --from=claude_mods . /opt/claude-mods
ENV CLAUDE_CODE_PLUGIN_CACHE_DIR=/opt/claude-seed
RUN HOME=/tmp/seed-home claude plugin marketplace add /opt/claude-mods \
 && HOME=/tmp/seed-home claude plugin install guard@claude-mods \
 && rm -rf /tmp/seed-home \
 && chmod -R a+rX,go-w /opt/claude-seed /opt/claude-mods
ENV CLAUDE_CODE_PLUGIN_SEED_DIR=/opt/claude-seed \
    CLAUDE_CODE_SYNC_PLUGIN_INSTALL=1

# Managed settings: the deny list, guard enabled. Project settings can't loosen them.
COPY --from=vigil_configs managed-settings.json /etc/claude-code/managed-settings.json

# Workers never push (P2: vigild pushes from the host). The hook refuses every
# push, and the system gitconfig points every repo at it.
COPY pre-push /opt/vigil/hooks/pre-push
RUN chmod 0555 /opt/vigil/hooks/pre-push \
 && git config --system core.hooksPath /opt/vigil/hooks \
 && git config --system safe.directory /work \
 && git config --system user.name "vigil-worker[bot]" \
 && git config --system user.email "vigil-worker[bot]@users.noreply.github.com"

COPY entrypoint.py /opt/vigil/entrypoint.py
COPY agent-cli /opt/vigil/agent-cli
RUN chmod 0555 /opt/vigil/agent-cli && command -v setpriv

# The harness is PID 1 as root (runtime.py adds only SETUID, SETGID and KILL);
# it runs the CLI, test_cmd and git as uid 10001 with no capabilities, so the
# agent can't reach its stdout or signal it (review round 2, N1 and N11).
USER 0:0
ENV HOME=/tmp/home \
    CLAUDE_CONFIG_DIR=/tmp/home/.claude \
    CLAUDE_CODE_ENABLE_TELEMETRY=1 \
    CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1 \
    OTEL_TRACES_EXPORTER=otlp \
    OTEL_METRICS_EXPORTER=otlp \
    OTEL_LOGS_EXPORTER=otlp \
    OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \
    OTEL_LOG_TOOL_DETAILS=1 \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    PYTHONUNBUFFERED=1
WORKDIR /work
ENTRYPOINT ["python", "/opt/vigil/entrypoint.py"]
