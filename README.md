# Forge Product Agent

Forge is a local, interactive Python agent that helps turn an idea into a maintainable product. It starts with brainstorming, records an agreed product brief, proposes a small design, plans vertical slices, implements with tests, and verifies the result before calling it done.

The default configuration tries Groq first and automatically retries quota or rate-limit failures (HTTP 402/429) against the local LM Studio model identified as `forge-local`. The fallback remains active for the rest of that Forge process; restart Forge to try Groq again. Other provider errors remain visible so authentication and configuration mistakes are not hidden.

Its workspace tools use the Model Context Protocol (MCP). The included MCP server is deliberately narrow: it can only operate inside one configured workspace, hides common secret files, refuses stale overwrites, never invokes a shell, limits command families, truncates large outputs, and asks you to approve every write or process execution.

## Important: rotate the keys shared in chat

API keys pasted into a chat should be treated as exposed. Revoke the Groq and Hugging Face credentials previously shared, create replacements, and use only the replacements below. This repository contains no real key and does not load `.env` files.

## Install on Windows

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

## What “safe MCP” means here

- Only the bundled, reviewed stdio server is loaded. There is no one-click installation of registry servers.
- The MCP subprocess gets an intentionally small environment and receives no model-provider API key.
- Only five exact tool names reach the model. Their server descriptions and schema annotations are discarded; the host supplies short, trusted descriptions.
- Read results are treated as untrusted data. Writes and commands require an exact, visible approval each time.
- Existing files can be changed only after reading them and supplying their current SHA-256 digest.
- File access is rooted, symlink escapes are rejected, and common credential paths and key formats are denied.
- Commands use an argument array with `shell=False`. Python is limited to selected check/test modules and Git to read-only subcommands.

These controls reduce risk; they are not an operating-system sandbox. Running tests executes code from the workspace with your user permissions. Use a disposable VM or container for untrusted repositories. See [SECURITY.md](SECURITY.md) for the threat model.

## Design choices

Forge borrows the productive parts of the Superpowers workflow—Socratic brainstorming, explicit design approval, small plans, test-first implementation, review, and evidence before completion—without installing its full plugin framework. It uses the official MCP Python SDK instead of maintaining a private protocol implementation. Groq and Hugging Face are called through their OpenAI-compatible APIs with Python's standard library, avoiding separate provider SDKs.

## Develop and test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src tests
```

Architecture, research, and extension guidance live in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/RESEARCH.md](docs/RESEARCH.md), and [docs/ADDING_MCP.md](docs/ADDING_MCP.md).
