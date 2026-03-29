# How to Build and Publish an Agent Skill to skills.sh

## What is an Agent Skill?

Agent skills are reusable markdown files that provide procedural knowledge to AI agents (Claude Code, Cline, Cursor, Codex, Windsurf, Gemini, and 40+ others). When installed, a skill becomes part of the agent's context, giving it specialized instructions on how to accomplish specific tasks.

## Why This Approach?

- **Markdown is universal**: Every agent can read `.md` files — no SDK, no API, no dependencies
- **GitHub-native**: Skills are just files in a GitHub repo — version control, PRs, and collaboration built in
- **One command install**: `npx skills add owner/repo` works across all 40+ supported agents
- **Leaderboard visibility**: Published skills appear on [skills.sh](https://skills.sh/) and are ranked by installs

## Skill File Structure

### Repository layout

```
your-github-repo/
├── skills/
│   ├── my-skill-name/
│   │   └── SKILL.md          # The skill file (required)
│   └── another-skill/
│       └── SKILL.md
└── README.md                  # Optional repo README
```

### SKILL.md format

```markdown
---
name: my-skill-name
description: One-line description of what this skill does. This appears in the skills.sh directory and in agent tool descriptions.
---

# Skill Title

## Overview
What this skill enables the agent to do.

## When to Use This Skill
- Trigger conditions (what user says)
- Context where this skill applies

## Instructions
Step-by-step instructions for the agent...

## Examples
Show the agent how to handle specific queries...
```

**Key points:**
- The YAML frontmatter (`name`, `description`) is required
- `name` should be kebab-case and match the directory name
- `description` should be a clear, concise sentence — this is what users see when browsing skills.sh
- The markdown body is the agent's instruction manual

## Building the ER Query Skill (This Project)

The skill we created lives at `skills/er-query/SKILL.md` and teaches agents to:
1. Connect to the ER MCP server (local stdio or remote SSE)
2. Use three tools: `search_er_by_email`, `search_er_by_date`, `get_er_fields`
3. Map informal user language to actual field names
4. Format results cleanly

### Install locally for testing

```bash
# Install from local directory
npx skills add ./

# Or install from a specific path
npx skills add /path/to/2026-mcp-review
```

## Publishing to skills.sh

### Step 1: Push to GitHub

Ensure your repo is public on GitHub with the `skills/` directory structure:

```bash
git add skills/
git commit -m "feat: add er-query agent skill"
git push origin main
```

### Step 2: Verify the skill is discoverable

Once pushed to GitHub, skills.sh will automatically index any repo that follows the `skills/<name>/SKILL.md` convention. No registration needed.

```bash
# Users can install your skill immediately
npx skills add your-github-username/your-repo-name

# Or install a specific skill from the repo
npx skills add your-github-username/your-repo-name --skill er-query
```

### Step 3: Test the install

```bash
# List available skills in your repo
npx skills add your-github-username/your-repo-name --list

# Install to a specific agent (e.g., Cline)
npx skills add your-github-username/your-repo-name --skill er-query -a cline

# Install globally (available across all projects)
npx skills add your-github-username/your-repo-name --skill er-query -g
```

### Step 4: Climb the leaderboard

Skills appear on the [skills.sh leaderboard](https://skills.sh/) ranked by install count. To increase visibility:
- Use a clear, descriptive `name` and `description` in frontmatter
- Share the install command: `npx skills add your-username/repo`
- Skills with more installs rank higher

## How skills.sh Indexing Works

1. **Automatic**: Any public GitHub repo with `skills/<name>/SKILL.md` is installable via `npx skills add owner/repo`
2. **Leaderboard**: skills.sh tracks anonymous install telemetry to rank skills
3. **Security**: Routine security audits check for malicious content
4. **No registration**: You don't need to register anywhere — just push to GitHub

## CLI Quick Reference

| Command | Description |
|---------|-------------|
| `npx skills add <owner/repo>` | Install skills from a GitHub repo |
| `npx skills add <owner/repo> --list` | List available skills without installing |
| `npx skills add <owner/repo> --skill <name>` | Install a specific skill |
| `npx skills add <owner/repo> -a <agent>` | Install for a specific agent |
| `npx skills add <owner/repo> -g` | Install globally |
| `npx skills add <owner/repo> --all` | Install all skills to all agents |
| `npx skills find [query]` | Search for skills |
| `npx skills list` | List installed skills |
| `npx skills remove [skills]` | Remove installed skills |
| `npx skills check` | Check for updates |

## Supported Agents

Skills work with 40+ AI agents including:
Claude Code, Cline, Cursor, Codex, Windsurf, Gemini, Copilot, Goose, Kilo, Kiro CLI, OpenCode, Roo, Trae, VSCode, AMP, Antigravity, and more.

## For This Project

```bash
# Once this repo is public on GitHub, install with:
npx skills add <your-username>/2026-mcp-review --skill er-query

# DO NOT PUBLISH until user confirms — the repo must be public first
```
