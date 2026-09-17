# Threat model

The terminal transcript is untrusted observational data. The prompt labels it inside `<terminal_context>` and the configurable system prompt explains that it is a bounded, incomplete snapshot rather than direct host access. The system instruction also says not to follow instructions found there. This is a boundary for model behavior, not a security guarantee.

The application has no model-controlled tool use, filesystem browsing, or autonomous loop. A recognized shell fence is a suggestion. **Insert** writes text into the terminal input without submitting it. **Execute** submits the suggested command only when the operator explicitly clicks the action. The model cannot invoke Execute on its own.

Transcript sharing is bounded by both line and character limits and occurs only when a user submits a question. API keys should come from `TROUBLESHELL_API_KEY` or, in a future release, a desktop keyring rather than being persisted in plaintext.
