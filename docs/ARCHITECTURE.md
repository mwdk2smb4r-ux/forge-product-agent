# Architecture

```text
terminal user
    |
    v
Forge CLI -- approval gate -- OpenAI-compatible model endpoint
    |
    | official MCP 2.0 over local stdio
    v
bundled workspace MCP server
    |
    +-- rooted file operations
    +-- allowlisted, shell-free checks
```

`forge_agent.agent.ProductAgent` owns the conversation and bounded tool loop. `OpenAICompatibleProvider` is the only model adapter. `WorkspaceMCP` starts the bundled server, converts its selected tools to sanitized model schemas, and serializes results as untrusted data. `ApprovalGate` is the host-side policy authority. The server repeats path and command enforcement so a provider cannot bypass it by crafting tool arguments.

The workflow prompt is intentionally process-oriented rather than framework-oriented. It asks for an approved product brief before implementation, favors small vertical slices and standard-library solutions, documents material decisions, and requires test or inspection evidence for completion.

Session snapshots are optional and local. They are never loaded automatically, preventing stale or poisoned history from silently becoming trusted context.
