# Project instructions

## Storage

- Do not create task outputs, downloads, dependencies, caches, build artifacts, or temporary file contents on C:.
- Keep this project's generated files inside the current workspace. Use `workspace-env.cmd` for subprocesses and `workspace_runtime.configure_workspace()` for Python tools.
- Before running subprocesses, set TEMP and TMP to `D:\CodexData\tmp`, then redirect project temporary files to the workspace's `.runtime\tmp` before tools run.
- Reading existing programs and credentials from C: is allowed. Do not install dependencies there.
- Preserve the portable deployment's storage configuration when updating the project.

## Git workflow

- The user's fork is `origin`: `git@github.com:huang46u/entp-manual.git`.
- The original repository is `upstream`: `https://github.com/TANGuoGUO/entp-manual.git`. Use it for reference and updates; do not push to it.
- The user has authorized committing and pushing completed project changes to their fork. After making and verifying changes, create a descriptive commit and push the current branch to `origin` without asking for confirmation again.
- Exclude personal databases, Markdown records, backups, logs, caches, temporary files, and virtual environments from commits. Inspect the staged diff before committing.
- Do not force-push or overwrite remote work. If authentication or a remote conflict blocks a push, preserve the local commit and report the exact blocker.
- This workflow applies to agent-assisted changes. Edits made outside an active agent task require a subsequent agent request or a manual commit and push; no background file watcher is configured.
