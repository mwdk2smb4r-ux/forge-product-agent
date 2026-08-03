# Changelog

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
