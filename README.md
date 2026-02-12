# ClickUp Chat Backup Tool

Backup **all** conversations from your ClickUp workspace — channels, personal DMs, group DMs, and thread replies.

## What Gets Backed Up

| Type | Description |
|------|-------------|
| **Channels** | Public and private group chat channels |
| **Direct Messages** | Personal 1-on-1 conversations |
| **Group DMs** | Multi-person private chats |
| **Thread Replies** | Replies/threads on any message |
| **Legacy Chat Views** | Old-style Chat views (v2 API) |

## Quick Start

### 1. Get Your ClickUp API Token

1. Open ClickUp → click your avatar (bottom-left)
2. Go to **Settings** → **Apps**
3. Under **API Token**, click **Generate**
4. Copy the token (starts with `pk_`)

### 2. Install & Run

```bash
# Clone the repo
git clone <repo-url>
cd clickup-chat-backup

# Install dependencies
pip install -r requirements.txt

# Set up your token
cp .env.example .env
# Edit .env and paste your API token

# Run the backup
python3 backup_clickup_chats.py
```

### 3. That's It!

The script will:
- List your workspaces and let you pick one
- Scan for all channels, DMs, group DMs
- Download every message and thread reply
- Save everything in JSON + CSV

## Output Files

Backups are saved to `backups/<workspace-name>_<timestamp>/`:

```
backups/
└── MyWorkspace_20260212_120000/
    ├── all_conversations.json     # Everything in one file
    ├── all_conversations.csv
    ├── channels.json              # Only channels
    ├── channels.csv
    ├── direct_messages.json       # Only personal DMs
    ├── direct_messages.csv
    ├── group_dms.json             # Only group DMs
    ├── group_dms.csv
    ├── chat_views.json            # Legacy chat views
    ├── chat_views.csv
    └── backup_summary.json        # Stats
```

## Options

```bash
# Specify token directly (instead of .env)
python3 backup_clickup_chats.py --token pk_your_token_here

# Skip interactive selection — provide workspace ID
python3 backup_clickup_chats.py --workspace-id 1234567

# Faster backup — skip thread replies
python3 backup_clickup_chats.py --no-replies

# Skip legacy chat views scan
python3 backup_clickup_chats.py --skip-legacy

# Custom output directory
python3 backup_clickup_chats.py --output-dir /path/to/backups

# Combine options
python3 backup_clickup_chats.py --workspace-id 1234567 --no-replies --skip-legacy
```

## Token Security

- Your API token is stored in `.env` which is **git-ignored**
- Never commit your `.env` file
- The `backups/` folder is also git-ignored
- Rotate your token if it's ever exposed

## Requirements

- Python 3.8+
- `requests` and `python-dotenv` (installed via `requirements.txt`)

## Notes

- The script respects ClickUp API rate limits with automatic retry
- Large workspaces with many DMs may take a while — thread replies add extra API calls
- Use `--no-replies` for a faster initial backup
- Each user can only access conversations they are a member of — admin tokens get the most coverage
