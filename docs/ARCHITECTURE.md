# Architecture

```text
terminal user
    |
    v
Forge CLI -- approval gate -- OpenAI-compatible model endpoint
    |
    +-- optional metadata-only tracing --> allowlisted Langfuse HTTPS endpoint
    |
    +-- official MCP 2.0 over local stdio --> bundled workspace server
    |                                      +-- rooted file operations
    |                                      +-- allowlisted, shell-free checks
    |
    +-- official MCP 2.0 over local stdio --> isolated research server
                                           +-- bounded public HTTPS fetch
                                           +-- unauthenticated public GitHub API
                                           +-- optional Perplexity Search API
```

`forge_agent.agent.ProductAgent` owns the conversation and bounded tool loop. `OpenAICompatibleProvider` is the only model adapter. `WorkspaceMCP` starts both bundled servers, exposes only host-selected tools with sanitized schemas, routes each call to its owning process, and serializes results as untrusted data. `ApprovalGate` is the host-side policy authority. Each server repeats its own path, command, or network enforcement so a provider cannot bypass policy with crafted arguments.

The research server is intentionally separate from the workspace server. It has no workspace root and cannot call file or process tools. Its HTTPS client ignores proxy and cookie state, validates and pins public DNS results, rechecks redirects, bounds response bytes, accepts a small textual content-type set, and strips active HTML elements. The host passes only the optional dedicated Perplexity credential to this process.

The workflow prompt is intentionally process-oriented rather than framework-oriented. It asks for an approved product brief before implementation, favors small vertical slices and standard-library solutions, documents material decisions, and requires test or inspection evidence for completion.

Session snapshots are optional and local. They are never loaded automatically, preventing stale or poisoned history from silently becoming trusted context.

Tracing is a host-side adapter and is not part of either MCP process. A dedicated OpenTelemetry provider prevents unrelated application spans from being exported. Each user turn is a root `agent` observation; generation and tool observations are siblings beneath it, while a random session identifier groups turns until `/new`. Stable observation names keep dashboards usable. The adapter fails open for telemetry only—generation and safety controls continue to work—and flushes its bounded queue when Forge exits.
