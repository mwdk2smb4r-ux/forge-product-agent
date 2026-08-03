# Changelog

## 0.2.0 - 2026-08-03

- Added an isolated, read-only research MCP server.
- Added approved public HTTPS text fetching with DNS pinning, SSRF defenses, redirect validation, content limits, and active-HTML removal.
- Added unauthenticated read-only inspection of public GitHub repositories, releases, directories, and UTF-8 files.
- Added optional Perplexity Search API support using a dedicated credential.
- Expanded the host allowlist from five to eight tools and required approval for every outbound request.
- Added research configuration, threat-model documentation, live compatibility checks, and security-focused tests.

## 0.1.0 - 2026-08-03

- Initial public release with Groq-to-LM-Studio fallback and a bounded workspace MCP server.
