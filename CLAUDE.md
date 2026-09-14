# Agent Instructions

- The motto is simplicity but correctness.
- The docs might be outdated so always refer to code as the source of truth.
- Keep code simple, do not overengineer, and avoid test for unlikely edge cases that bloat code (Just inform me if you sense possible edge cases and I will decide for myself).
- Use ASD-STE100 simplified technical english when communicating or with comments.
- Do not add claude as co-author to any commits.

## Testing guidelines

- If you need to run tests for the server module for python, use the `.venv` venv environment.

## Coding style customization per personal preferences

- Ensure code is modular and maintainable over the long run. Avoid too much code complexity.

## Hard Boundaries

- Never add tracked workstation-absolute paths, local usernames, local machine ips, personal email addresses, secrets, private keys, tokens, passwords, or private certificates in tracked files, docs, runbooks, examples, generated snapshots, or helper comments.

## Working Defaults

- Keep docs generic, lean, consistent, and assumption-free. A human or agent should not need chat history to follow the tracked flow.
- Regenerate [docs](./docs) after big changes.
