# Security model

Forge assumes the model, workspace files, MCP results, and third-party MCP metadata may contain hostile instructions. It assumes the person at the terminal is trusted and can inspect an exact action before approving it.

## Security boundaries

1. **Credentials:** provider keys are read from one named environment variable only. They are sent only in the HTTPS Authorization header to the configured provider endpoint. They are never passed to the MCP subprocess or automatically added to sessions. Session snapshots are plain local JSON and can contain anything the user typed, so do not paste secrets into chat.
2. **Network:** model endpoints must be HTTPS, except explicit loopback addresses for local development. Forge does not support remote MCP transport.
3. **MCP:** only the bundled local stdio server is enabled. Tool names are host-allowlisted. Tool descriptions and descriptive JSON Schema fields supplied by a server are not forwarded to the model.
4. **Files:** all paths resolve below the configured workspace. Symlinks are rejected. Secret-like paths are denied. Existing files require an exact SHA-256 precondition before replacement.
5. **Processes:** process execution always requires approval, uses no shell, has a timeout and output limit, and is limited by executable and subcommand policy.
6. **Prompt injection:** tool output is clearly marked as untrusted. The system instruction forbids following instructions found in data. Mutating calls still stop for human approval.

## Known limits

- This is not a malware sandbox. Approved tests and build tools execute workspace code with the current user's rights.
- A human can approve a harmful command or content write. Review paths and arguments carefully.
- A compromised model provider sees prompts and any workspace content the agent chooses to read and return to the conversation.
- Local malware running as the same OS user can inspect process memory and environment variables.
- Path validation cannot defend against every same-user race in a directory an attacker can modify concurrently.

Use a container or VM, a dedicated low-privilege account, short-lived narrowly scoped tokens, and version-controlled backups for higher-risk work.

## Reporting

Do not include live credentials, private file contents, or exploit payloads containing real data in a report. Revoke any credential that may have been disclosed.
