# Adding another MCP server safely

Forge intentionally does not accept arbitrary MCP startup commands from configuration. A local MCP command is code execution with the same privileges as Forge, and registry popularity is not a security review.

Before extending `WorkspaceMCP`:

1. Pin the server to an immutable version and verify its publisher and source.
2. Review its startup command, install scripts, dependencies, network behavior, and update path.
3. Run it in an OS sandbox or container with only the directories and network destinations it needs.
4. Pass individual required environment variables; never inherit the whole parent environment.
5. Allowlist exact tool names. Replace server-supplied descriptions with locally reviewed purposes and sanitize schemas.
6. Classify every tool. Require per-call approval for writes, messages, purchases, permission changes, process execution, or data transmission.
7. Bound time, input size, output size, redirects, and retries. For HTTP transports, implement the current MCP OAuth requirements and SSRF protections instead of inventing token handling.
8. Add tests that prove denied tools never reach the model and rejected calls never reach the server.

Prefer a small purpose-built server over a general shell, filesystem, browser, or “do anything” server.
