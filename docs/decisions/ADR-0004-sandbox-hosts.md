# ADR-0004: Sandbox hosts

- **Status:** proposed, 2026-10-27. Code starts after the owner approves this ADR.
- **Deciders:** the owner. Recorded by vigil-coord.
- **Related:** issue #8 (vigil bench). The design note and the owner's decisions are its 2026-10-27 comments.

## Context
vigil runs every session and every grader in the local Docker Desktop. On the Mac mini that is linux/arm64.

Every benchmark source vigil bench uses ships linux/amd64 images, and no arm64 ones were found: SWE-PolyBench, SWE-bench Pro V2 and SWE-bench Live. Under Rosetta, the measured cost is a 2.8–5.3× CPU slowdown. Two Pro V2 tasks still graded in 12–22 s (#8). That's fine for a pilot, but routine Core runs want native x86.

The owner's ruling, 2026-10-27:
- Hosts that run models and hosts that run sandboxes are **separate concepts**.
- A sandbox host is **generic**, and no code names a specific machine.

## Decision

### 1. Config: `sandbox_hosts`
`configs/sandbox_hosts.yaml` holds a list. Each entry has these fields:

| Field | Meaning |
|---|---|
| `name` | Free text, used in logs and doctor output. |
| `docker_context` | A Docker context name. The local Docker is the built-in default entry, `local`. |
| `arch` | `arm64` or `amd64`. Checked against `docker info`. |
| `memory_gb`, `cpus` | The caps of the host's dedicated slice. |
| `disk_budget_gb` | The most space vigil's images and containers may use. |
| `uses` | Any of `jobs` and `bench`. `local` defaults to both. |
| `gateway_url` | How this host's containers reach vigild's gateway. For `local` this is `http://host.docker.internal:8788`. |

Model hosts stay in `configs/backends.yaml` as they are. **No code in `vigild/` names a machine.** A test fails on any host name in `vigild/` that isn't read from config.

### 2. Scheduling
- **Architecture match.** A task runs on a host whose `arch` matches its image's architecture, read from the image manifest.
- **Normal jobs** run on `local`. Their images are built locally, so they're arm64. A host takes normal jobs only if `uses` lists `jobs`, and today only `local` does.
- **Bench tasks** go to a host whose `arch` is `amd64` and whose `uses` includes `bench`.
- **When no x86 bench host is configured:**
  - `bench.allow_emulation: true` runs the task on `local` under Rosetta. The run is labelled `emulated`, its timeouts are scaled, and a timeout is tagged `environment`. These are the pilot rules in #8.
  - Otherwise the run is refused, with a clear reason.
- **The verifier grades on the same host as the session**, in the task's derived image, with `--network none`.

### 3. Rules every remote sandbox host must meet
Doctor checks every rule, and vigild refuses to start if a configured remote host fails one.

1. **SSH only, private network only.**
   - The Docker context endpoint is `ssh://…`. A `tcp://` endpoint is refused.
   - The SSH target must resolve to a private address (RFC 1918, or the 100.64.0.0/10 range a private overlay network uses).
   - The SSH key lives on the vigild host. The sandbox host holds no secrets.
2. **A pinned Docker Engine running with userns-remap or rootless mode.**
   - The engine version must equal the pin in `configs/sandbox_hosts.yaml`.
   - `docker info` must show `userns` or `rootless` in its security options.
3. **Egress only to vigild's gateway.**
   - Each session gets its own `internal: true` network and a smokescreen sidecar on that host. The sidecar's allowlist is exactly the host's `gateway_url`.
   - Doctor runs a probe container on the host. It must reach the gateway's health route. It must fail to reach the internet, the host's own other ports, any other address on the private network, and every model endpoint in `configs/backends.yaml`.
4. **No GPU.**
   - vigild never passes device requests or `--gpus`.
   - Doctor fails if the host's default runtime is a GPU runtime, or if the probe container sees a GPU device node.
5. **Caps in a dedicated slice.**
   - Every container vigild creates on the host gets `cgroup_parent` set to the host's vigil slice.
   - Doctor's probe reads that slice's memory and CPU limits, and fails if they're missing or larger than `memory_gb` or `cpus`.
6. **A disk budget, enforced by pruning.**
   - vigild prunes **only its own labelled** images and containers, least recently used first, when usage passes `disk_budget_gb`. That matches #26's rule: a cleanup only ever touches what carries vigil's own label.
   - Doctor reports usage against the budget.

These carry over **unchanged on every host**, local or remote:
- **Container flags:** `--read-only`, `--cap-drop ALL`, `no-new-privileges`, and pids and memory limits.
- **The agent user:** uid 10001.
- **No bind mounts.** Files go in only through `docker cp` or a tar stream over the Docker API.
- **No GitHub token** in any container.

### 4. The gateway on a private interface
- A remote sandbox host's containers reach the gateway at that host's `gateway_url`. So vigild also listens on its private-network address when any remote host is configured, and only then. The bind address is set in config.
- The per-session gateway token is unchanged.
- The private network's access rules should let only sandbox hosts reach the gateway port. This is the operator's network config; doctor states the rule but can't verify it from the vigild side.

### 5. Docs
- **`docs/runbook.md`:**
  - **"One machine with Docker"** stays the default path, with no sandbox host config needed.
  - **"Add a sandbox host"** is a new optional section: the six rules, how to create the SSH context and slice, and doctor's checks.
- **The owner's own setup** goes in a separate deployment note under `docs/deploy/`: a specific x86 machine on the owner's private network, configured as a sandbox host for bench. It carries no addresses, because the repo is public.

## Consequences
- The bench pilot can run natively on an x86 sandbox host, and on the Mac mini under emulation where no such host is configured.
- vigild gains a host-selection step before every session and grader run. For normal jobs it always picks `local`, so their behaviour is unchanged.
- Doctor grows a probe container per remote host. Each probe takes seconds and runs only when a remote host is configured.
- A machine that also serves models can be a sandbox host only if it passes rules 3–5. Its model ports must be unreachable from sandboxes, and the slice keeps sandboxes from starving the model server.

## Alternatives considered
- **Emulation only.** Simplest, and kept as the fallback. But it's 2.8–5.3× slower on CPU-bound suites, and an emulation timeout tells us nothing about the model.
- **A Docker TCP socket, with or without TLS.** Rejected: a network-exposed daemon socket is root on the host. SSH over a private network keeps the daemon off the network.
- **Naming the x86 machine in code**, for example as a special case of the model host. Rejected by the owner: model hosts and sandbox hosts are separate, and the product must work on one machine.
- **Normal jobs on remote hosts too.** Deferred. `uses: [jobs]` allows it later, but today normal jobs stay local.

## Open questions for the owner
1. Should the Docker Engine pin be one version for every host, or one per host?
2. Is `bench.allow_emulation` on by default for the pilot? Proposed: yes, until the x86 host passes doctor.
