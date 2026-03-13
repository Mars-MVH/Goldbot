---
name: conventional-commits
description: Enforces Conventional Commits specification for all git commit messages. Analyzes changes and generates or corrects semantic commit messages (feat:, fix:, refactor:, docs:, chore:, etc.). Apply automatically before suggesting or making commits.
version: 1.0
---

# Conventional Commits Skill

You enforce the Conventional Commits specification to create consistent, semantic, machine-readable git history.

## Specification (must follow exactly)
Format:  
`<type>[optional scope]: <short description>`

Optional body (blank line after subject):  
`Detailed explanation. Why was this change made? What does it affect?`

Optional footer:  
`BREAKING CHANGE: description`  
`Fixes #123`  
`Closes #456`

## Allowed Types (use the most appropriate)
- feat:     new feature
- fix:      bug fix
- refactor: code change that neither fixes a bug nor adds a feature
- docs:     documentation only
- style:    formatting, missing semicolons, etc. (no code change)
- test:     adding or correcting tests
- chore:    maintenance tasks (deps, tooling)
- build:    build system or external dependencies
- ci:       CI configuration
- perf:     performance improvement
- revert:   revert previous commit

## Rules
- Subject line: max 72 characters, imperative mood ("add", "fix", not "added", "fixed")
- Scope: optional, e.g. feat(auth): ..., refactor(ui/components):
- No period at end of subject
- Use lowercase for type and scope
- If breaking change → include BREAKING CHANGE footer or ! after type (feat!: ...)
- Analyze staged changes / diff to infer correct type & description
- Never allow vague messages ("wip", "update", "fix bug")

## Workflow Integration
- Before suggesting git commit → generate full Conventional Commit message
- If user provides bad message → correct it and explain why
- On commit proposals → always output in correct format
- Suggest squashing or splitting commits if scope is too broad

## Output Style
- When proposing commit: show full message with body/footer if needed
- Flag violations: "This message does not follow Conventional Commits — corrected version:"

Activate automatically when: suggesting commits, reviewing git history, preparing PRs, or any git-related task.