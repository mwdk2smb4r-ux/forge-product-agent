# Research and framework choices

The supplied [Multiverse AI Toolkit](https://start.me/p/RMPGL5/multiverse-ai-toolkit) was reviewed as a discovery hub. The most relevant entries were MCP's official project and server collection, fast-agent, the linked MCP security checklists, OWASP prompt-injection guidance, local/open model tools, and the agent-workflow resources.

## Adopted

- [MCP Python SDK 2.0](https://github.com/modelcontextprotocol/python-sdk): the current official protocol implementation, used as the sole direct runtime dependency.
- [MCP security best practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices): informed stdio-only transport, minimal subprocess environment, explicit consent, local server allowlisting, bounded privileges, and no arbitrary startup commands.
- [MCP 2026-07-28 stdio transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports): used through the SDK rather than a private protocol implementation.
- [Superpowers](https://github.com/obra/superpowers): informed the brainstorm → approved design → small plan → test-first slices → review → verification workflow.
- [Groq local tool calling](https://console.groq.com/docs/tool-use/local-tool-calling): informed the bounded model/tool loop and OpenAI-compatible message format.
- [OWASP prompt-injection prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html): informed the assumption that retrieved content and tool output are untrusted.

## Considered but not imported

- [fast-agent](https://github.com/evalstate/fast-agent) is capable and supports Groq, Hugging Face, MCP, skills, and agent deployment. Forge's first version needs one interactive agent, one local MCP server, and a visible approval gate. A small host keeps that gate auditable and avoids bringing in a general multi-agent runtime before it adds product value.
- Superpowers itself is a plugin/skills framework for existing coding harnesses. Forge incorporates the relevant lifecycle in its system instruction instead of coupling this standalone CLI to a particular harness.
- Public MCP registries are useful discovery sources, not trust authorities. Forge intentionally has no registry installer or arbitrary MCP command configuration.

This is a YAGNI decision, not a permanent rejection. A framework should be reconsidered when the product genuinely needs orchestration, remote deployment, multiple agents, or a broader provider matrix.
