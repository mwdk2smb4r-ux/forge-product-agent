# Changelog

## 0.4.0 - 2026-08-03

- Added optional Langfuse 4.14.1 tracing with one trace per turn, session grouping, generation/tool observations, model identity, token usage, approvals, and safe error types.
- Made tracing opt-in and metadata-only by default; prompts, responses, file contents, tool arguments, and results are excluded unless content capture is explicitly enabled.
- Pinned the Langfuse destination to an HTTPS allowlist, isolated its OpenTelemetry provider, kept its credentials out of MCP subprocesses, and made telemetry failures non-fatal.
- Added secure PowerShell setup guidance, a Windows lock snapshot for the tracing extra, doctor/status visibility, shutdown flushing, and tracing security tests.

## 0.3.0 - 2026-08-03

- Blocked execution of project Python tests, linters, and npm scripts by default; syntax compilation and read-only Git inspection remain available.
- Added an explicit `workspace.allow_project_code_execution` trusted-project override.
- Required per-file approval before a remote model can read workspace contents while keeping local-model reads local.
- Bound known Groq and Hugging Face credential variables to their official HTTPS API endpoints.
- Expanded secret-file blocking to cover environment variants and common credential stores.
- Added weekly Dependabot checks and a Windows dependency lock snapshot.
- Made a missing primary credential fall back safely to an available local provider.

## 0.2.0 - 2026-08-03

- Added an isolated, read-only research MCP server.
- Added approved public HTTPS text fetching with DNS pinning, SSRF defenses, redirect validation, content limits, and active-HTML removal.
- Added unauthenticated read-only inspection of public GitHub repositories, releases, directories, and UTF-8 files.
- Added optional Perplexity Search API support using a dedicated credential.
- Expanded the host allowlist from five to eight tools and required approval for every outbound request.
- Added research configuration, threat-model documentation, live compatibility checks, and security-focused tests.

## 0.1.0 - 2026-08-03

- Initial public release with Groq-to-LM-Studio fallback and a bounded workspace MCP server.
