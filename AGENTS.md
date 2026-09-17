# Workspace conventions

- User-selected root: `C:\Users\aryam\Desktop\yee\coding\resumeproject`.
- Store project artifacts here, not in Downloads or unrelated profile folders.
- Shared idea notes belong in `docs/ideas/`.
- Relay planning and research belong in `docs/relay/`.
- When authorized, implement Relay under `relay/` within this workspace. This supersedes the older standalone implementation path in the historical plan.
- Keep application code, tests and dependency manifests together; do not scatter them among planning documents.
- Do not move or modify the original resume unless requested.
- A planning or organization request does not authorize implementing the application.
- Inspect existing files before edits; preserve user changes and verify created or moved files.

## Version control and GitHub

- This workspace is its own git repository (nested inside the accidental home-directory repo; always operate with `-C` on this path).
- Remote: `origin` = `https://github.com/AryamanSharma14/resumeproject.git` (private). Keep it private until the user explicitly approves publishing (Phase A/decision point).
- After each completed, verified unit of work: commit with a specific message, push to `origin/main`, and verify the push (local and remote HEAD SHA match) before reporting success. Never report "pushed" without that verification.
- Never commit secrets, tokens, or files matching `.gitignore`; scan before committing when anything sensitive might be present.
- Commit messages: imperative, specific ("Add X", "Fix Y"), no vague "updates".
- Do not force-push or rewrite published history.
- Never create placeholder/stub application modules to make checks pass; a feature exists only when implemented and tested per the roadmap.
