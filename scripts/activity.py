"""Aggregate recent GitHub activity into profile/activity.json.

Only totals, timestamps and language names leave this script. Repository names,
owners and descriptions are read to compute totals and are never written.

    GH_TOKEN=... python scripts/activity.py [output path]

The token must belong to the profile owner so that private activity counts.
"""

import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

API = "https://api.github.com"
ROOT = Path(__file__).resolve().parent.parent
WINDOW_DAYS = 30
LANGUAGE_LIMIT = 4
REPOSITORY_PAGE_LIMIT = 10

REPOSITORIES = """
query($after: String) {
  viewer {
    login
    repositories(first: 100, after: $after, isFork: false,
                 ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER],
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { pushedAt owner { login } primaryLanguage { name } }
    }
  }
}
"""

CALENDAR = """
query {
  viewer {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def request(token: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "profile-activity",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.load(response)
    if isinstance(payload, dict) and payload.get("errors"):
        raise RuntimeError(f"GitHub API error: {payload['errors']}")
    return payload


def graphql(token: str, query: str, variables: dict | None = None) -> dict:
    return request(token, "/graphql", {"query": query, "variables": variables or {}})["data"]


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def recent_repositories(token: str, since: datetime) -> tuple[str, list[dict]]:
    """Repositories pushed since `since`, newest first, plus the viewer login."""
    found, after = [], None
    for _ in range(REPOSITORY_PAGE_LIMIT):
        viewer = graphql(token, REPOSITORIES, {"after": after})["viewer"]
        page = viewer["repositories"]
        for node in page["nodes"]:
            if not node["pushedAt"] or parse_time(node["pushedAt"]) < since:
                return viewer["login"], found
            found.append(node)
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return viewer["login"], found


def latest_event(token: str, login: str) -> datetime | None:
    # Events are the account's own actions; authenticated as the owner they include private ones.
    events = request(token, f"/users/{login}/events?per_page=30")
    stamps = [parse_time(e["created_at"]) for e in events if e.get("created_at")]
    return max(stamps, default=None)


def collect(token: str, now: datetime) -> dict:
    since = now - timedelta(days=WINDOW_DAYS)
    login, repositories = recent_repositories(token, since)

    # Pushes to owned repositories are the owner's; collaborator repositories also carry other people's pushes.
    owned_push = max(
        (parse_time(r["pushedAt"]) for r in repositories if r["owner"]["login"] == login),
        default=None,
    )
    candidates = [t for t in (latest_event(token, login), owned_push) if t is not None]

    languages = Counter(r["primaryLanguage"]["name"] for r in repositories if r["primaryLanguage"])

    calendar = graphql(token, CALENDAR)["viewer"]["contributionsCollection"]["contributionCalendar"]
    days = sorted(
        (d for week in calendar["weeks"] for d in week["contributionDays"]),
        key=lambda d: d["date"],
    )
    end = date.fromisoformat(days[-1]["date"])
    by_day = {d["date"]: d["contributionCount"] for d in days}
    window = [by_day.get((end - timedelta(days=offset)).isoformat(), 0) for offset in range(WINDOW_DAYS - 1, -1, -1)]

    return {
        "generatedAt": now.isoformat(timespec="seconds"),
        "lastActiveAt": max(candidates).astimezone(timezone.utc).isoformat(timespec="seconds") if candidates else None,
        "windowDays": WINDOW_DAYS,
        "contributionsYear": calendar["totalContributions"],
        "contributionsWindow": sum(window),
        "daily": window,
        "dailyEnd": end.isoformat(),
        "activeRepositories": len(repositories),
        "languages": [name for name, _ in languages.most_common(LANGUAGE_LIMIT)],
    }


def main() -> None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GH_TOKEN is not set")
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "profile" / "activity.json"
    activity = collect(token, datetime.now(timezone.utc).replace(microsecond=0))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(activity, indent=2) + "\n")
    print(f"last active {activity['lastActiveAt']}, {activity['contributionsWindow']} contributions in {WINDOW_DAYS} days")


if __name__ == "__main__":
    main()
