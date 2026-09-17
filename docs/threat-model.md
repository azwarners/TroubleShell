# Threat model

The terminal transcript is untrusted observational data. The prompt labels it inside `<terminal_context>` and the configurable system prompt explains that it is a bounded, incomplete snapshot rather than direct host access. The system instruction also says not to follow instructions found there. This is a boundary for model behavior, not a security guarantee.

The application has no tool, command execution, filesystem browsing, or autonomous loop. A recognized shell fence is only a suggestion. **Insert** writes text into the terminal input; the operator reviews it and executes it manually.

Transcript sharing is bounded by both line and character limits and occurs only when a user submits a question. API keys should come from `TROUBLESHELL_API_KEY` or, in a future release, a desktop keyring rather than being persisted in plaintext.
