"""Renders dark_mode.svg and light_mode.svg from template.svg with live GitHub stats.

GITHUB_TOKEN must be USERNAME's classic PAT with `repo`. Anything narrower
returns smaller totals without an error, so it is refused. Contributions in
repos even that token cannot read are in the calendar total only.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import Template
from xml.sax.saxutils import escape

USERNAME = "dmriding"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API_URL = "https://api.github.com/graphql"
ROOT = Path(__file__).parent
BAR_WIDTH = 150
TOP_LANGS = 10
LANG_COLUMN = 400  # x offset of the second language column
NAME_MAX = 17  # characters that fit between a bar and its percent
REPO_CAP = 100  # API maximum for commitContributionsByRepository

PALETTES = {
    "dark_mode.svg": {
        "bg": "#0d1117", "titlebar": "#161b22", "border": "#30363d",
        "fg": "#e6edf3", "muted": "#7d8590", "key": "#58a6ff",
        "accent": "#f0883e", "green": "#3fb950", "track": "#21262d",
        "close": "#f85149",
    },
    "light_mode.svg": {
        "bg": "#ffffff", "titlebar": "#f6f8fa", "border": "#d0d7de",
        "fg": "#1f2328", "muted": "#656d76", "key": "#0550ae",
        "accent": "#bf3100", "green": "#1a7f37", "track": "#eaeef2",
        "close": "#f85149",
    },
}

PROFILE_QUERY = """
query($login: String!) {
  viewer { login }
  user(login: $login) {
    createdAt
    pullRequests(states: MERGED) { totalCount }
    public: repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC) {
      nodes { stargazerCount }
    }
  }
}
"""

COMMITS_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar { totalContributions }
      commitContributionsByRepository(maxRepositories: 100) {
        contributions { totalCount }
        repository {
          languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
            edges { size node { name color } }
          }
        }
      }
    }
  }
}
"""


def has_repo_scope(header: str) -> bool:
    """Exact match: `public_repo` must not pass. Guard: test_today.TokenGate."""
    return "repo" in [scope.strip() for scope in header.split(",")]


def graphql(query: str, variables: dict) -> dict:
    req = urllib.request.Request(
        API_URL,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        scopes = resp.headers.get("X-OAuth-Scopes", "")
        body = json.loads(resp.read())
    if not has_repo_scope(scopes):
        sys.exit("GITHUB_TOKEN is not a classic token with the `repo` scope")
    if body.get("errors"):
        # Types only: messages can name private orgs and Actions logs here are public.
        sys.exit("GraphQL error: " + ", ".join(sorted({str(e.get("type")) for e in body["errors"]})))
    return body["data"]


def commit_windows(start: datetime, end: datetime):
    """Yields contributions for [start, end); halves a window that hits
    REPO_CAP, because the API drops the repos past the cap without saying so."""
    coll = graphql(COMMITS_QUERY, {
        "login": USERNAME,
        "from": start.isoformat(),
        "to": (end - timedelta(seconds=1)).isoformat(),
    })["user"]["contributionsCollection"]
    days = (end - start).days
    if len(coll["commitContributionsByRepository"]) >= REPO_CAP and days > 1:
        mid = start + timedelta(days=days // 2)
        yield from commit_windows(start, mid)
        yield from commit_windows(mid, end)
    else:
        yield coll


def percent_rows(weights: dict) -> list:
    """(name, pct) for the top languages plus a real Other, summing to 100 by
    largest remainder. Guard: test_today.PercentRows."""
    total = sum(weights.values())
    if not total:
        return []
    ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    rows = ranked[:TOP_LANGS]
    rest = sum(w for _, w in ranked[TOP_LANGS:])
    if rest:
        rows.append(("Other", rest))
    exact = [w / total * 100 for _, w in rows]
    pcts = [int(x) for x in exact]
    by_remainder = sorted(range(len(rows)), key=lambda i: exact[i] - pcts[i], reverse=True)
    for i in by_remainder[: 100 - sum(pcts)]:
        pcts[i] += 1
    return [(name, pct) for (name, _), pct in zip(rows, pcts)]


def fetch_stats() -> dict:
    data = graphql(PROFILE_QUERY, {"login": USERNAME})
    if data["viewer"]["login"].lower() != USERNAME.lower():
        sys.exit(f"GITHUB_TOKEN does not belong to {USERNAME}")
    user = data["user"]
    contributions, commits_year, hidden, weights, colors = 0, 0, 0, {}, {}
    this_year = datetime.now(timezone.utc).year
    for year in range(int(user["createdAt"][:4]), this_year + 1):
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        for coll in commit_windows(start, start.replace(year=year + 1)):
            contributions += coll["contributionCalendar"]["totalContributions"]
            hidden += coll["restrictedContributionsCount"]
            if year == this_year:
                commits_year += coll["totalCommitContributions"]
            for entry in coll["commitContributionsByRepository"]:
                # A repo's commits are split across its languages by byte share.
                edges = entry["repository"]["languages"]["edges"]
                size = sum(e["size"] for e in edges)
                if not size:
                    continue
                for e in edges:
                    name = e["node"]["name"]
                    share = entry["contributions"]["totalCount"] * e["size"] / size
                    weights[name] = weights.get(name, 0) + share
                    colors[name] = e["node"]["color"]

    return {
        "stars": sum(r["stargazerCount"] for r in user["public"]["nodes"]),
        "contributions": contributions,
        "commits_year": commits_year,
        "prs_merged": user["pullRequests"]["totalCount"],
        "hidden": hidden,
        "languages": [(name, pct, colors.get(name)) for name, pct in percent_rows(weights)],
    }


def lang_rows(languages: list, palette: dict) -> str:
    rows = []
    per_column = -(-len(languages) // 2)
    for i, (name, pct, color) in enumerate(languages):
        x, y = i // per_column * LANG_COLUMN, i % per_column * 20
        width = max(3, round(pct / 100 * BAR_WIDTH))
        label = name if len(name) <= NAME_MAX else name[: NAME_MAX - 1] + "…"
        rows.append(
            f'<rect x="{x}" y="{y}" width="{BAR_WIDTH}" height="10" rx="3" fill="{palette["track"]}" />'
            f'<rect x="{x}" y="{y}" width="{width}" height="10" rx="3" fill="{color or palette["muted"]}" />'
            f'<text x="{x + 160}" y="{y + 10}" font-size="12" fill="{palette["fg"]}">{escape(label)}</text>'
            f'<text x="{x + 285}" y="{y + 10}" font-size="12" fill="{palette["muted"]}">{pct or "&lt;1"}%</text>'
        )
    return "\n    ".join(rows)


def main():
    if not TOKEN:
        sys.exit("GITHUB_TOKEN not set")
    stats = fetch_stats()
    languages = stats.pop("languages")
    print(stats)
    for name, pct, _ in languages:
        print(f"  {name}: {pct}%")

    template = Template((ROOT / "template.svg").read_text(encoding="utf-8"))
    numbers = {key: f"{value:,}" for key, value in stats.items()}
    cards = {
        filename: template.substitute(palette | numbers, lang_rows=lang_rows(languages, palette))
        for filename, palette in PALETTES.items()
    }
    for filename, svg in cards.items():
        (ROOT / filename).write_text(svg, encoding="utf-8")
        print(f"wrote {filename}")


if __name__ == "__main__":
    main()
