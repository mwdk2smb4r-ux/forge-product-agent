# Forge Product Agent

Forge is a local, interactive Python agent that helps turn an idea into a maintainable product. It starts with brainstorming, records an agreed product brief, proposes a small design, plans vertical slices, implements with tests, and verifies the result before calling it done.

The default configuration tries Groq first and automatically retries quota or rate-limit failures (HTTP 402/429) against the local LM Studio model identified as `forge-local`. The fallback remains active for the rest of that Forge process; restart Forge to try Groq again. Other provider errors remain visible so authentication and configuration mistakes are not hidden.

Its tools use the Model Context Protocol (MCP). The workspace server is deliberately narrow: it can only operate inside one configured workspace, hides common secret files, refuses stale overwrites, never invokes a shell, limits command families, and asks you to approve every write or process execution.

Forge v0.2 also includes a separate read-only research MCP server. It can fetch bounded text from public HTTPS pages, inspect public GitHub repositories, and optionally search through Perplexity. Every network request shows its exact arguments and requires approval. The research process receives no Groq or Hugging Face credential and has no workspace tools.

## Important: rotate the keys shared in chat

API keys pasted into a chat should be treated as exposed. Revoke the Groq and Hugging Face credentials previously shared, create replacements, and use only the replacements below. This repository contains no real key and does not load `.env` files.

## Install on Windows

Forge requires Python 3.11 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
$env:GROQ_API_KEY = Read-Host "Paste your NEW Groq API key"
.\.venv\Scripts\forge-agent.exe
```

The default workspace is `product_workspace`. Forge creates it on first run.

Useful commands in the chat:

- `/help` shows commands.
- `/status` shows the provider, model, workspace, and session size.
- `/tools` shows the MCP tools and which ones require approval.
- `/save optional-name` writes a local session snapshot under `.forge_agent/sessions`.
- `/new` clears the conversation after confirmation.
- `/quit` exits.

For a one-off prompt:

```powershell
.\.venv\Scripts\forge-agent.exe --message "Help me explore an idea for a meal planning app."
```

To check configuration without sending data to a model:

```powershell
.\.venv\Scripts\forge-agent.exe --doctor
```

## Hugging Face or a local OpenAI-compatible endpoint

Change `provider` in `forge.toml` to `huggingface`, set a model supported by the Hugging Face router, and set a replacement token:

```powershell
$env:HF_TOKEN = Read-Host "Paste your NEW Hugging Face token"
```

For a local service such as Ollama, add a provider section and select it:

```toml
[agent]
provider = "local"
model = "your-local-model"

[providers.local]
base_url = "http://127.0.0.1:11434/v1"
api_key_env = ""
```

Provider fallback is configured in `[agent]`:

```toml
provider = "groq"
model = "openai/gpt-oss-120b"
fallback_providers = ["local"]

[providers.local]
base_url = "http://127.0.0.1:1234/v1"
api_key_env = ""
model = "forge-local"
```

LM Studio must be running when fallback is needed. Forge announces each fallback in the terminal.

Interactive responses are labeled with the provider and API model identifier that actually produced them, for example `forge [local/forge-local]>`. The host also injects these runtime facts into every model request because a model's unsupported claims about its own identity are not reliable. Use `/status` for the authoritative provider and execution location.

Only loopback HTTP is allowed. Non-local providers must use HTTPS.

## Safe public research

Direct URL and public GitHub research work without another API key. Ask Forge to research a public URL or repository; before any request leaves the computer, Forge displays the exact tool arguments and requires you to type `yes`.

Optional general web search uses Perplexity's Search API. It is disabled at call time until you provide a dedicated key:

```powershell
$secret = Read-Host "Enter your Perplexity API key" -AsSecureString
$env:PERPLEXITY_API_KEY = [System.Net.NetworkCredential]::new("", $secret).Password
```

The token is passed only to the isolated research subprocess and only to `https://api.perplexity.ai/search`. Perplexity search is a paid external service; direct URL and public GitHub research remain available without it. To remove search from the tool entirely, use:

```toml
[research]
search_provider = "none"
```

To restrict direct page fetching to selected sites, configure an allowlist. Subdomains are included:

```toml
[research]
allowed_domains = ["python.org", "github.com"]
```

Research controls include HTTPS port 443 only, DNS resolution pinned to validated public addresses, private/local/reserved address rejection, redirect revalidation, response and timeout limits, an explicit content-type allowlist, no compression, no cookies, no JavaScript, and no browser or login state. HTML scripts, styles, templates, SVG, and other active content are removed before text reaches the model.

## What “safe MCP” means here

- Only the two bundled, reviewed stdio servers are loaded. There is no one-click installation of registry servers or remote MCP transport.
- Both MCP subprocesses get intentionally small environments. Neither receives a model-provider API key; the research process may receive only `PERPLEXITY_API_KEY` when explicitly configured.
- Only eight exact tool names reach the model. Server descriptions and descriptive schema annotations are discarded; the host supplies short, trusted descriptions.
- All results are treated as untrusted data. Writes, commands, and every outbound research request require an exact, visible approval each time.
- Existing files can be changed only after reading them and supplying their current SHA-256 digest.
- File access is rooted, symlink escapes are rejected, and common credential paths and key formats are denied.
- Commands use an argument array with `shell=False`. Python is limited to selected check/test modules and Git to read-only subcommands.

These controls reduce risk; they are not an operating-system sandbox. Running tests executes code from the workspace with your user permissions. Use a disposable VM or container for untrusted repositories. See [SECURITY.md](SECURITY.md) for the threat model.

## Design choices

Forge borrows the productive parts of the Superpowers workflow—Socratic brainstorming, explicit design approval, small plans, test-first implementation, review, and evidence before completion—without installing its full plugin framework. It uses the official MCP Python SDK instead of maintaining a private protocol implementation. Model providers and public research endpoints are called with Python's standard library, avoiding separate provider, search, HTML, and GitHub SDK dependencies.

## Develop and test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src tests
```

Architecture, research, and extension guidance live in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/RESEARCH.md](docs/RESEARCH.md), and [docs/ADDING_MCP.md](docs/ADDING_MCP.md).

Release history is recorded in [CHANGELOG.md](CHANGELOG.md).
