---
name: next-task
description: Implement the "Next task" from docs/tasks.md end to end, mark it done, and write the following task for the next agent. Owner-triggered only.
disable-model-invocation: true
---

# Next task

You implement exactly one task: the one under "## Next task" in
`docs/tasks.md`. Then you hand over to the next agent. Assume you have no
prior context; the repo docs are your memory.

## 1. Prepare

1. Read `AGENTS.md` and its reading list (`local/MACHINE.md` if present,
   `docs/decisions.md`, `docs/roadmap.md`).
2. Read `docs/tasks.md`. The "Next task" section is your assignment. Read every
   doc and file it references.
3. Run `git status` and `git pull --ff-only`. If the tree is dirty or the pull
   fails, stop and ask the owner.
4. If the task needs owner approval (downloads, installs, PCSX2 config, deleting
   outside the repo), ask now, before starting. If the task is unclear or
   blocked, stop and ask. Don't guess.

## 2. Implement

- Follow the task's scope and steps. Nothing outside them.
- Follow `CLAUDE.md`: simple code, surgical changes, existing patterns,
  minimal comments.
- Write the tests the task asks for. Run them.
- Check every success criterion on real data. Look at outputs, not only exit codes.
- Keep game data and anything game-specific out of git (`work/` and `local/` are ignored).

If a criterion can't be met, stop and tell the owner what happened. Don't mark
the task done.

## 3. Update the docs

- Game-specific findings → `local/games/<serial>/notes.md` (git-ignored; never in tracked files).
- New decisions → append to `docs/decisions.md`.
- Phase status → `docs/roadmap.md`.
- Anything the task said to document.

## 4. Hand over

In `docs/tasks.md`:

1. Add a row to "## Done": task ID and title, date, one-line summary. Leave the
   commit cell as `this commit`.
2. Replace "## Next task" with the top backlog item, written in full, using the
   same structure as before: **Goal**, **Context**, **Scope**,
   **Success criteria**, **Out of scope**. Use what you learned.
3. Remove that item from the backlog. Add, reorder or split backlog items if
   you learned something that requires it.

Task size: one big chunk that one agent can finish in one session. Split
anything bigger. Flag tasks that need owner approval at the top of their scope.

## 5. Commit

1. `git status`: only generic code and docs. No game data, nothing game-specific (`local/`, `work/` stay untracked).
2. One commit: `T<n>: <title>`.
3. Ask the owner before pushing.

## 6. Report

Short report to the owner: what was built, how it was verified, anything
unverified, and the new next task.
