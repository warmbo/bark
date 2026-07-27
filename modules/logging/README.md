# Logging Module

Comprehensive event and file logging for server activity.

## Events Logged

| Event Type | Description | Config Key |
|------------|-------------|------------|
| Message Edits | Before/after content of edited messages | `message_edit` |
| Message Deletes | Deleted messages including attachments | `message_delete` |
| File Uploads | Files uploaded with download URLs and sizes | `file_upload` |
| Member Joins | New members joining the server | `member_join` |
| Member Leaves | Members leaving or being removed | `member_leave` |
| Voice State | Voice channel joins, leaves, and moves | `voice_state` |

## Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `/logsetup` | Configure a logging channel for an event type | Manage Guild |
| `/logstatus` | View current logging configuration | Anyone |
| `/logfiles` | Search recent file uploads by member or type | Manage Guild |

## Events (EventBus)

- `discord_message` — File attachment tracking
- `discord_message_edit` — Edit logging
- `discord_message_delete` — Delete logging
- `discord_member_join` — Join logging
- `discord_member_remove` — Leave logging
- `discord_voice_state` — Voice state logging

## Database Tables

- `log_configs` — Per-event-type channel mapping (slash command config)
- `file_attachments` — File metadata (name, size, type, URL, author)

## Configuration

Configured via the module detail page (`/guild/{id}/modules/logging`).
Each event type has:
- `channel_id` — Where logs for this event are posted
- `enabled` — Whether logging is active

Configuration is stored in `ModuleConfig` (dashboard) and `LogConfig` (slash commands).
The logging system checks both, preferring dashboard configuration.
