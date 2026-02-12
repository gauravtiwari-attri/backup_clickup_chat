#!/usr/bin/env python3
"""
ClickUp Chat Backup Tool
Author: Gaurav Tiwari

Backs up ALL conversations from a ClickUp workspace:
  - Channels (public/private group chats)
  - Direct Messages (personal 1-on-1 chats)
  - Group DMs (multi-person private chats)
  - Thread replies on messages
  - Legacy Chat Views (v2 API)

Saves data in both JSON and CSV formats.
"""

import argparse
import requests
import json
import csv
import os
import time
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load .env file from script directory
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ─── Configuration ───────────────────────────────────────────────────────────

API_TOKEN = os.environ.get("CLICKUP_API_TOKEN", "")
BASE_URL_V2 = "https://api.clickup.com/api/v2"
BASE_URL_V3 = "https://api.clickup.com/api/v3"

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
RATE_LIMIT_DELAY = 1.0  # seconds between API calls
MAX_RETRIES = 3


# ─── API Helpers ─────────────────────────────────────────────────────────────

def get_headers():
    return {
        "Authorization": API_TOKEN,
        "Content-Type": "application/json",
    }


def api_get(url, params=None, retries=0):
    """Make a GET request with rate limiting, retries, and error handling."""
    time.sleep(RATE_LIMIT_DELAY)
    try:
        resp = requests.get(url, headers=get_headers(), params=params, timeout=30)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            print(f"  Rate limited. Waiting {retry_after}s...")
            time.sleep(retry_after)
            return api_get(url, params)
        if resp.status_code == 401:
            print("  ERROR: Invalid API token. Check your CLICKUP_API_TOKEN.")
            sys.exit(1)
        if resp.status_code != 200:
            print(f"  API error {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json()
    except requests.exceptions.RequestException as e:
        if retries < MAX_RETRIES:
            wait = 2 ** (retries + 1)
            print(f"  Connection error, retrying in {wait}s... ({retries + 1}/{MAX_RETRIES})")
            time.sleep(wait)
            return api_get(url, params, retries + 1)
        print(f"  Request failed after {MAX_RETRIES} retries: {e}")
        return None


# ─── Workspace / Team ────────────────────────────────────────────────────────

def get_teams():
    """Get all workspaces (teams) the user has access to."""
    data = api_get(f"{BASE_URL_V2}/team")
    if data and "teams" in data:
        return data["teams"]
    return []


def get_workspace_members(team_id):
    """Get all members in a workspace to resolve DM names."""
    data = api_get(f"{BASE_URL_V2}/team/{team_id}")
    members = {}
    if data and "team" in data:
        for member in data["team"].get("members", []):
            user = member.get("user", {})
            uid = str(user.get("id", ""))
            members[uid] = {
                "name": user.get("username", user.get("initials", "Unknown")),
                "email": user.get("email", ""),
            }
    return members


def select_workspace(workspace_id=None):
    """Let user select a workspace, or auto-select if ID is provided."""
    teams = get_teams()
    if not teams:
        print("No workspaces found. Check your API token.")
        sys.exit(1)

    # Auto-select by ID if provided
    if workspace_id:
        for team in teams:
            if str(team["id"]) == str(workspace_id):
                print(f"\nSelected workspace: {team['name']}")
                return team
        print(f"Workspace ID '{workspace_id}' not found.")
        sys.exit(1)

    print("\nAvailable workspaces:")
    for i, team in enumerate(teams):
        print(f"  [{i + 1}] {team['name']} (ID: {team['id']})")

    if len(teams) == 1:
        print(f"\nAuto-selected: {teams[0]['name']}")
        return teams[0]

    while True:
        try:
            choice = int(input("\nSelect workspace number: ")) - 1
            if 0 <= choice < len(teams):
                return teams[choice]
        except (ValueError, KeyboardInterrupt):
            pass
        print("Invalid selection. Try again.")


# ─── Legacy Chat Views (v2 API) ─────────────────────────────────────────────

def get_spaces(team_id):
    """Get all spaces in a workspace."""
    data = api_get(f"{BASE_URL_V2}/team/{team_id}/space", params={"archived": "false"})
    if data and "spaces" in data:
        return data["spaces"]
    return []


def get_folders(space_id):
    """Get all folders in a space."""
    data = api_get(f"{BASE_URL_V2}/space/{space_id}/folder", params={"archived": "false"})
    if data and "folders" in data:
        return data["folders"]
    return []


def get_views_for_space(space_id):
    """Get all views in a space."""
    data = api_get(f"{BASE_URL_V2}/space/{space_id}/view")
    if data and "views" in data:
        return data["views"]
    return []


def get_views_for_folder(folder_id):
    """Get all views in a folder."""
    data = api_get(f"{BASE_URL_V2}/folder/{folder_id}/view")
    if data and "views" in data:
        return data["views"]
    return []


def get_views_for_list(list_id):
    """Get all views in a list."""
    data = api_get(f"{BASE_URL_V2}/list/{list_id}/view")
    if data and "views" in data:
        return data["views"]
    return []


def get_lists_for_folder(folder_id):
    """Get all lists in a folder."""
    data = api_get(f"{BASE_URL_V2}/folder/{folder_id}/list", params={"archived": "false"})
    if data and "lists" in data:
        return data["lists"]
    return []


def get_folderless_lists(space_id):
    """Get lists not in a folder."""
    data = api_get(f"{BASE_URL_V2}/space/{space_id}/list", params={"archived": "false"})
    if data and "lists" in data:
        return data["lists"]
    return []


def get_chat_view_comments(view_id):
    """Get ALL comments from a chat view (handles pagination)."""
    all_comments = []
    start = None
    start_id = None

    while True:
        params = {}
        if start is not None:
            params["start"] = start
        if start_id is not None:
            params["start_id"] = start_id

        data = api_get(f"{BASE_URL_V2}/view/{view_id}/comment", params=params)
        if not data or "comments" not in data or len(data["comments"]) == 0:
            break

        comments = data["comments"]
        all_comments.extend(comments)
        print(f"    Fetched {len(all_comments)} comments so far...")

        if len(comments) < 25:
            break

        oldest = comments[-1]
        start = oldest.get("date")
        start_id = oldest.get("id")

        if start is None or start_id is None:
            break

    return all_comments


def find_all_chat_views(team_id):
    """Discover all chat views across all spaces, folders, and lists."""
    chat_views = []
    spaces = get_spaces(team_id)
    print(f"\nFound {len(spaces)} space(s)")

    for space in spaces:
        space_name = space["name"]
        space_id = space["id"]
        print(f"\n  Scanning space: {space_name}")

        # Views at space level
        views = get_views_for_space(space_id)
        for v in views:
            if v.get("type") == "chat":
                chat_views.append({
                    "view_id": v["id"],
                    "view_name": v.get("name", "Unnamed"),
                    "location": f"Space: {space_name}",
                })

        # Folders in space
        folders = get_folders(space_id)
        for folder in folders:
            folder_name = folder["name"]
            folder_id = folder["id"]

            views = get_views_for_folder(folder_id)
            for v in views:
                if v.get("type") == "chat":
                    chat_views.append({
                        "view_id": v["id"],
                        "view_name": v.get("name", "Unnamed"),
                        "location": f"Space: {space_name} > Folder: {folder_name}",
                    })

            lists = get_lists_for_folder(folder_id)
            for lst in lists:
                list_name = lst["name"]
                list_id = lst["id"]
                views = get_views_for_list(list_id)
                for v in views:
                    if v.get("type") == "chat":
                        chat_views.append({
                            "view_id": v["id"],
                            "view_name": v.get("name", "Unnamed"),
                            "location": f"Space: {space_name} > Folder: {folder_name} > List: {list_name}",
                        })

        # Folderless lists
        lists = get_folderless_lists(space_id)
        for lst in lists:
            list_name = lst["name"]
            list_id = lst["id"]
            views = get_views_for_list(list_id)
            for v in views:
                if v.get("type") == "chat":
                    chat_views.append({
                        "view_id": v["id"],
                        "view_name": v.get("name", "Unnamed"),
                        "location": f"Space: {space_name} > List: {list_name}",
                    })

    return chat_views


# ─── New Chat Channels & Messages (v3 API) ──────────────────────────────────

def get_all_channels(workspace_id):
    """Get chat channels the user follows, plus all DMs and Group DMs (including closed)."""
    all_channels = []
    seen_ids = set()

    # Fetch only channels the user follows + all DMs/Group DMs (including closed)
    for include_closed in ["false", "true"]:
        cursor = None
        while True:
            params = {
                "limit": 100,
                "is_follower": "true",
                "include_closed": include_closed,
            }
            if cursor:
                params["cursor"] = cursor

            data = api_get(
                f"{BASE_URL_V3}/workspaces/{workspace_id}/chat/channels",
                params=params,
            )
            if not data or "data" not in data:
                break

            channels = data["data"]
            for ch in channels:
                if ch["id"] not in seen_ids:
                    seen_ids.add(ch["id"])
                    all_channels.append(ch)

            print(f"  Fetched {len(all_channels)} unique channels so far... (include_closed={include_closed})")

            next_cursor = data.get("next_cursor")
            if not next_cursor:
                break
            cursor = next_cursor

    return all_channels


def get_channel_messages(workspace_id, channel_id):
    """Get ALL messages from a chat channel."""
    all_messages = []
    cursor = None

    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor

        data = api_get(
            f"{BASE_URL_V3}/workspaces/{workspace_id}/chat/channels/{channel_id}/messages",
            params=params,
        )
        if not data:
            break

        messages = data.get("data", data.get("messages", []))
        if not messages:
            break

        all_messages.extend(messages)
        print(f"    Fetched {len(all_messages)} messages so far...")

        next_cursor = data.get("next_cursor")
        if not next_cursor:
            break
        cursor = next_cursor

    return all_messages


def get_message_replies(workspace_id, channel_id, message_id):
    """Get all replies/threads for a specific message."""
    all_replies = []
    cursor = None

    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor

        data = api_get(
            f"{BASE_URL_V3}/workspaces/{workspace_id}/chat/channels/{channel_id}/messages/{message_id}/replies",
            params=params,
        )
        if not data:
            break

        replies = data.get("data", data.get("replies", []))
        if not replies:
            break

        all_replies.extend(replies)

        next_cursor = data.get("next_cursor")
        if not next_cursor:
            break
        cursor = next_cursor

    return all_replies


def resolve_channel_name(channel, members):
    """Resolve a friendly name for DM channels using member info."""
    ch_name = channel.get("name", "")
    ch_type = channel.get("type", "")

    if ch_name and ch_type == "CHANNEL":
        return ch_name

    # For DMs, try to build name from members
    if ch_type in ("DM", "GROUP_DM"):
        member_links = channel.get("member_links", channel.get("members", []))
        names = []
        for m in member_links:
            uid = str(m.get("user_id", m.get("id", "")))
            if uid in members:
                names.append(members[uid]["name"])
        if names:
            return f"DM: {' & '.join(names)}"

    return ch_name if ch_name else f"channel-{channel.get('id', 'unknown')}"


# ─── Export Helpers ──────────────────────────────────────────────────────────

def extract_text(content):
    """Extract plain text from various message content formats."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    if isinstance(content, dict):
        return content.get("text", content.get("plain_text", json.dumps(content)))
    return str(content)


def format_timestamp(ts):
    """Convert Unix timestamp (ms) to readable datetime."""
    if not ts:
        return ""
    try:
        ts_val = int(ts) / 1000 if int(ts) > 1e12 else int(ts)
        return datetime.fromtimestamp(ts_val).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return str(ts)


def save_json(data, filepath):
    """Save data as formatted JSON."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"  Saved: {filepath}")


def save_chat_views_csv(all_view_data, filepath):
    """Save chat view comments as CSV."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "View Name", "Location", "Comment ID", "Date", "User",
            "User Email", "Message Text", "Resolved", "Reply Count",
        ])
        for view_info in all_view_data:
            for comment in view_info.get("comments", []):
                user = comment.get("user", {}) or {}
                writer.writerow([
                    view_info.get("view_name", ""),
                    view_info.get("location", ""),
                    comment.get("id", ""),
                    format_timestamp(comment.get("date")),
                    user.get("username", user.get("initials", "")),
                    user.get("email", ""),
                    extract_text(comment.get("comment", comment.get("comment_text", ""))),
                    comment.get("resolved", ""),
                    comment.get("reply_count", "0"),
                ])
    print(f"  Saved: {filepath}")


def save_channels_csv(all_channel_data, filepath):
    """Save chat channel messages as CSV."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Channel Name", "Channel Type", "Message ID", "Date",
            "User", "User Email", "Message Text", "Is Reply",
            "Parent Message ID", "Reactions", "Attachments",
        ])
        for ch_info in all_channel_data:
            ch_name = ch_info.get("channel_name", "")
            ch_type = ch_info.get("channel_type", "")

            for msg in ch_info.get("messages", []):
                _write_message_row(writer, ch_name, ch_type, msg, is_reply=False)

                # Write replies as sub-rows
                for reply in msg.get("replies", []):
                    _write_message_row(
                        writer, ch_name, ch_type, reply,
                        is_reply=True, parent_id=msg.get("id", ""),
                    )
    print(f"  Saved: {filepath}")


def _write_message_row(writer, ch_name, ch_type, msg, is_reply=False, parent_id=""):
    """Write a single message row to CSV."""
    user = msg.get("creator", msg.get("user", {})) or {}
    content = msg.get("content", msg.get("text", ""))
    text = extract_text(content)

    reactions = msg.get("reactions", [])
    reactions_str = json.dumps(reactions) if reactions else ""

    attachments = msg.get("attachments", [])
    attachment_str = ""
    if attachments:
        att_names = [a.get("name", a.get("url", "")) for a in attachments]
        attachment_str = "; ".join(att_names)

    writer.writerow([
        ch_name,
        ch_type,
        msg.get("id", ""),
        format_timestamp(msg.get("date_created", msg.get("date", ""))),
        user.get("username", user.get("name", "")),
        user.get("email", ""),
        text,
        "Yes" if is_reply else "No",
        parent_id,
        reactions_str,
        attachment_str,
    ])


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    global API_TOKEN

    parser = argparse.ArgumentParser(
        description="Backup all ClickUp chat conversations (channels, DMs, threads)",
    )
    parser.add_argument(
        "--token",
        help="ClickUp API token (or set CLICKUP_API_TOKEN env var / .env file)",
    )
    parser.add_argument(
        "--workspace-id",
        help="Workspace ID to backup (skips interactive selection)",
    )
    parser.add_argument(
        "--include-replies",
        action="store_true",
        default=True,
        help="Include thread replies for each message (default: true)",
    )
    parser.add_argument(
        "--no-replies",
        action="store_true",
        help="Skip fetching thread replies (faster backup)",
    )
    parser.add_argument(
        "--skip-legacy",
        action="store_true",
        help="Skip scanning for legacy Chat Views (v2 API)",
    )
    parser.add_argument(
        "--output-dir",
        help="Custom output directory for backups",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  ClickUp Chat Backup Tool")
    print("  Backs up: Channels + DMs + Group DMs + Threads")
    print("=" * 60)

    # Resolve API token
    if args.token:
        API_TOKEN = args.token
    if not API_TOKEN:
        API_TOKEN = input("\nEnter your ClickUp API token: ").strip()
    if not API_TOKEN:
        print("API token is required.")
        print("Set it via: --token, CLICKUP_API_TOKEN env var, or .env file")
        sys.exit(1)

    # Output directory
    output_dir = args.output_dir or OUTPUT_DIR

    # Select workspace
    workspace = select_workspace(args.workspace_id)
    workspace_id = workspace["id"]
    workspace_name = workspace["name"]

    # Resolve member names for DMs
    print("\nFetching workspace members...")
    members = get_workspace_members(workspace_id)
    print(f"Found {len(members)} member(s)")

    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(output_dir, f"{workspace_name}_{timestamp}")
    os.makedirs(backup_dir, exist_ok=True)

    total_comments = 0
    total_messages = 0
    total_replies = 0
    fetch_replies = args.include_replies and not args.no_replies

    # ── Part 1: Legacy Chat Views (v2) ───────────────────────────────────
    all_view_data = []
    chat_views = []

    if not args.skip_legacy:
        print("\n" + "-" * 60)
        print("Part 1: Scanning for legacy Chat Views...")
        print("-" * 60)

        chat_views = find_all_chat_views(workspace_id)
        print(f"\nFound {len(chat_views)} chat view(s)")

        for cv in chat_views:
            print(f"\n  Backing up: {cv['view_name']} ({cv['location']})")
            comments = get_chat_view_comments(cv["view_id"])
            total_comments += len(comments)
            all_view_data.append({
                "view_id": cv["view_id"],
                "view_name": cv["view_name"],
                "location": cv["location"],
                "comment_count": len(comments),
                "comments": comments,
            })

        if all_view_data:
            save_json(all_view_data, os.path.join(backup_dir, "chat_views.json"))
            save_chat_views_csv(all_view_data, os.path.join(backup_dir, "chat_views.csv"))

    # ── Part 2: All Chat Channels, DMs, Group DMs (v3) ──────────────────
    print("\n" + "-" * 60)
    print("Part 2: Fetching ALL conversations (Channels + DMs + Group DMs)...")
    print("-" * 60)

    channels = get_all_channels(workspace_id)

    # Categorize
    ch_channels = [c for c in channels if c.get("type") == "CHANNEL"]
    ch_dms = [c for c in channels if c.get("type") == "DM"]
    ch_group_dms = [c for c in channels if c.get("type") == "GROUP_DM"]
    ch_other = [c for c in channels if c.get("type") not in ("CHANNEL", "DM", "GROUP_DM")]

    print(f"\n  Channels:   {len(ch_channels)}")
    print(f"  DMs:        {len(ch_dms)}")
    print(f"  Group DMs:  {len(ch_group_dms)}")
    if ch_other:
        print(f"  Other:      {len(ch_other)}")
    print(f"  Total:      {len(channels)}")

    all_channel_data = []
    for idx, ch in enumerate(channels, 1):
        ch_type = ch.get("type", "unknown")
        ch_id = ch.get("id", "")
        ch_name = resolve_channel_name(ch, members)

        print(f"\n  [{idx}/{len(channels)}] {ch_name} (type: {ch_type})")

        messages = get_channel_messages(workspace_id, ch_id)
        total_messages += len(messages)

        # Fetch thread replies for messages that have them
        if fetch_replies:
            for msg in messages:
                reply_count = msg.get("reply_count", 0)
                if isinstance(reply_count, str):
                    reply_count = int(reply_count) if reply_count.isdigit() else 0
                if reply_count > 0:
                    msg_id = msg.get("id", "")
                    replies = get_message_replies(workspace_id, ch_id, msg_id)
                    msg["replies"] = replies
                    total_replies += len(replies)
                    if replies:
                        print(f"      Thread: {len(replies)} replies on message {msg_id}")

        all_channel_data.append({
            "channel_id": ch_id,
            "channel_name": ch_name,
            "channel_type": ch_type,
            "channel_info": ch,
            "message_count": len(messages),
            "messages": messages,
        })

    # Save all together
    if all_channel_data:
        save_json(all_channel_data, os.path.join(backup_dir, "all_conversations.json"))
        save_channels_csv(all_channel_data, os.path.join(backup_dir, "all_conversations.csv"))

        # Also save separately by type for easier browsing
        channels_only = [c for c in all_channel_data if c["channel_type"] == "CHANNEL"]
        dms_only = [c for c in all_channel_data if c["channel_type"] == "DM"]
        group_dms_only = [c for c in all_channel_data if c["channel_type"] == "GROUP_DM"]

        if channels_only:
            save_json(channels_only, os.path.join(backup_dir, "channels.json"))
            save_channels_csv(channels_only, os.path.join(backup_dir, "channels.csv"))
        if dms_only:
            save_json(dms_only, os.path.join(backup_dir, "direct_messages.json"))
            save_channels_csv(dms_only, os.path.join(backup_dir, "direct_messages.csv"))
        if group_dms_only:
            save_json(group_dms_only, os.path.join(backup_dir, "group_dms.json"))
            save_channels_csv(group_dms_only, os.path.join(backup_dir, "group_dms.csv"))

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Backup Complete!")
    print("=" * 60)
    print(f"  Workspace:       {workspace_name}")
    if not args.skip_legacy:
        print(f"  Chat Views:      {len(chat_views)} views, {total_comments} comments")
    print(f"  Channels:        {len(ch_channels)}")
    print(f"  Direct Messages: {len(ch_dms)}")
    print(f"  Group DMs:       {len(ch_group_dms)}")
    print(f"  Total Messages:  {total_messages}")
    print(f"  Thread Replies:  {total_replies}")
    print(f"  Backup Location: {backup_dir}")
    print("=" * 60)

    summary = {
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
        "backup_date": datetime.now().isoformat(),
        "chat_views_count": len(chat_views),
        "chat_view_comments_count": total_comments,
        "channels_count": len(ch_channels),
        "dms_count": len(ch_dms),
        "group_dms_count": len(ch_group_dms),
        "total_messages": total_messages,
        "total_thread_replies": total_replies,
        "files": {
            "all_conversations": "all_conversations.json / .csv",
            "channels_only": "channels.json / .csv",
            "direct_messages": "direct_messages.json / .csv",
            "group_dms": "group_dms.json / .csv",
            "chat_views": "chat_views.json / .csv (legacy)",
        },
    }
    save_json(summary, os.path.join(backup_dir, "backup_summary.json"))


if __name__ == "__main__":
    main()
