# Moderation Module

Server moderation with full case tracking and voice controls.

## Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `/warn` | Issue a warning to a member | Moderate Members |
| `/timeout` | Timeout a member for a duration | Moderate Members |
| `/kick` | Remove a member from the server | Kick Members |
| `/ban` | Permanently ban a member | Ban Members |
| `/unban` | Unban a user by ID | Ban Members |
| `/cases` | View recent moderation cases | Anyone |
| `/warnings` | View warnings for a member | Anyone |
| `/clearwarn` | Clear a warning by ID | Moderate Members |
| `/vc_kick` | Disconnect a member from voice | Mute Members |
| `/vc_move` | Move a member to another voice channel | Move Members |
| `/vc_mute` | Server-mute a member in voice | Mute Members |
| `/vc_unmute` | Server-unmute a member in voice | Mute Members |
| `/vc_deafen` | Server-deafen a member in voice | Deafen Members |
| `/vc_undeafen` | Server-undeafen a member in voice | Deafen Members |
| `/voice_sessions` | View voice session history | Moderate Members |

## Events

- `voice_state_change` — Tracks voice channel join/leave times in the database

## Database Tables

- `moderation_cases` — Every moderation action with case number
- `warnings` — Active warning records per user
- `voice_sessions` — Voice channel join/leave timestamps
- `audit_logs` — Structured audit trail for all actions

## Configuration

No configurable settings. All behavior is command-driven.

## Architecture

All moderation actions flow through `BarkContext`:
1. Command handler called
2. Case created via `ctx.create_case()`
3. Audit logged via `ctx.log_audit()`
4. Warning added via `ctx.add_warning()`
5. Discord API action executed via bot
