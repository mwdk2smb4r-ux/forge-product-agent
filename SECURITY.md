# Security model

Forge assumes the model, workspace files, MCP results, and third-party MCP metadata may contain hostile instructions. It assumes the person at the terminal is trusted and can inspect an exact action before approving it.

## Security boundaries

1. **Credentials:** provider keys are read from one named environment variable only. They are sent only in the HTTPS Authorization header to the configured provider endpoint. They are never passed to the MCP subprocess or automatically added to sessions. Session snapshots are plain local JSON and can contain anything the user typed, so do not paste secrets into chat.
2. **Network:** model endpoints must be HTTPS, except explicit loopback addresses for local development. Research accepts only public HTTPS on port 443. Hostnames are resolved before connecting, every resolved address must be globally routable, and the selected address is pinned for the TLS connection. Redirects are revalidated. Forge does not support remote MCP transport.
3. **MCP:** only the bundled workspace and research stdio servers are enabled. Tool names are host-allowlisted. Tool descriptions and descriptive JSON Schema fields supplied by a server are not forwarded to the model.
4. **Files:** all paths resolve below the configured workspace. Symlinks are rejected. Secret-like paths are denied. Existing files require an exact SHA-256 precondition before replacement.
5. **Processes:** process execution always requires approval, uses no shell, has a timeout and output limit, and is limited by executable and subcommand policy. Safe mode blocks project-code execution by default.
6. **Prompt injection:** tool output is clearly marked as untrusted. The system instruction forbids following instructions found in data. Mutating calls still stop for human approval.
7. **Research isolation:** the research server has no workspace path or workspace tools. It receives no model-provider credential. If configured, only `PERPLEXITY_API_KEY` is passed to that subprocess, and search is hard-coded to Perplexity's HTTPS endpoint. All network calls require exact user approval.
8. **Remote file consent:** local models may read bounded non-secret workspace text directly. Remote models require exact approval before each workspace file read.
9. **Credential destinations:** known provider credentials are bound to their official HTTPS endpoint so a configuration edit cannot redirect them to another host.

## Known limits

- This is not a malware sandbox. Safe mode blocks project tests and build scripts. If trusted-project execution is explicitly enabled, approved tools execute workspace code with the current user's rights.
- A human can approve a harmful command or content write. Review paths and arguments carefully.
- A compromised model provider sees prompts and any workspace content the agent chooses to read and return to the conversation.
- Local malware running as the same OS user can inspect process memory and environment variables.
- Path validation cannot defend against every same-user race in a directory an attacker can modify concurrently.
- Public research reveals the approved URL, hostname, GitHub repository coordinates, or search query to the relevant remote service. Do not approve queries containing secrets, private source, personal data, or unpublished product details.
- DNS and TLS pinning, content limits, and HTML stripping reduce network risk but do not make hostile content trustworthy. Research can still contain false claims or prompt injection.
- Public GitHub API access is unauthenticated and subject to GitHub's public rate limits.

Use a container or VM, a dedicated low-privilege account, short-lived narrowly scoped tokens, and version-controlled backups for higher-risk work.

## Reporting

Do not include live credentials, private file contents, or exploit payloads containing real data in a report. Revoke any credential that may have been disclosed.
