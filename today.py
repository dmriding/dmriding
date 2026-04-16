"""
Fetches GitHub stats for dmriding and updates the SVG templates.
Designed to run via GitHub Actions with GITHUB_TOKEN env var.
"""

import os
import json
import re
import urllib.request
import urllib.error

USERNAME = "dmriding"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
API_URL = "https://api.github.com/graphql"
SVG_FILES = ["dark_mode.svg", "light_mode.svg"]
BAR_MAX_WIDTH = 150

# Hardcode overrides (set to None to use live API values)
OVERRIDES = {
    "repos": 74,
    "stars": None,
    "commits": None,
}


def graphql(query: str, variables: dict | None = None) -> dict:
    """Execute a GitHub GraphQL query."""
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_stats() -> dict:
    """Fetch repos, stars, commits, and language breakdown."""
    from datetime import datetime

    # Get repos, stars, languages, and account creation date
    query = """
    query($login: String!) {
        user(login: $login) {
            createdAt
            repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC) {
                totalCount
                nodes {
                    stargazerCount
                    languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
                        edges {
                            size
                            node { name }
                        }
                    }
                }
            }
        }
    }
    """
    data = graphql(query, {"login": USERNAME})
    user = data["data"]["user"]
    repos = user["repositories"]

    # Count stars
    total_stars = sum(r["stargazerCount"] for r in repos["nodes"])

    # Count commits across ALL years (default query only covers last 365 days)
    created_year = int(user["createdAt"][:4])
    current_year = datetime.now().year
    total_commits = 0

    commits_query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
        user(login: $login) {
            contributionsCollection(from: $from, to: $to) {
                totalCommitContributions
                restrictedContributionsCount
            }
        }
    }
    """
    for year in range(created_year, current_year + 1):
        from_date = f"{year}-01-01T00:00:00Z"
        to_date = f"{year}-12-31T23:59:59Z"
        result = graphql(commits_query, {
            "login": USERNAME,
            "from": from_date,
            "to": to_date,
        })
        contribs = result["data"]["user"]["contributionsCollection"]
        total_commits += (
            contribs["totalCommitContributions"]
            + contribs["restrictedContributionsCount"]
        )
    print(f"  Summed commits across {current_year - created_year + 1} years")

    # Aggregate languages
    lang_sizes: dict[str, int] = {}
    for repo in repos["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            lang_sizes[name] = lang_sizes.get(name, 0) + edge["size"]

    total_size = sum(lang_sizes.values()) or 1
    top_langs = sorted(lang_sizes.items(), key=lambda x: x[1], reverse=True)

    # Build top 3: first two explicitly, rest as "Other"
    languages = []
    for i, (name, size) in enumerate(top_langs[:2]):
        languages.append({"name": name, "pct": round(size / total_size * 100)})
    other_pct = 100 - sum(l["pct"] for l in languages)
    if other_pct > 0:
        languages.append({"name": "Other", "pct": other_pct})

    return {
        "repos": repos["totalCount"],
        "stars": total_stars,
        "commits": total_commits,
        "languages": languages,
    }


def update_svg(filepath: str, stats: dict) -> None:
    """Update an SVG file with fresh stats using regex (preserves formatting)."""
    with open(filepath, "r", encoding="utf-8") as f:
        svg = f.read()

    def set_text(svg: str, element_id: str, value: str) -> str:
        """Replace text content of a <text id="...">...</text> element."""
        pattern = rf'(id="{element_id}"[^>]*>)[^<]*(</text>)'
        return re.sub(pattern, rf"\g<1>{value}\2", svg)

    def set_rect_width(svg: str, element_id: str, width: float) -> str:
        """Replace width attribute of a <rect id="..."> element."""
        w = str(max(3, int(width)))
        pattern = rf'(id="{element_id}"[^>]*\bwidth=")[^"]*(")'
        result = re.sub(pattern, rf"\g<1>{w}\2", svg)
        if result == svg:
            # id might appear before width in the attributes
            pattern = rf'(<rect[^>]*\bwidth=")([^"]*)"([^>]*id="{element_id}")'
            result = re.sub(pattern, rf'\g<1>{w}"\3', svg)
        return result

    # Update stats text
    svg = set_text(svg, "repos_data", str(stats["repos"]))
    svg = set_text(svg, "stars_data", str(stats["stars"]))
    svg = set_text(svg, "commits_data", str(stats["commits"]))

    # Update language bars and percentages
    lang_ids = [
        ("rust_bar", "rust_pct"),
        ("python_bar", "python_pct"),
        ("other_bar", "other_pct"),
    ]
    for i, (bar_id, pct_id) in enumerate(lang_ids):
        if i < len(stats["languages"]):
            lang = stats["languages"][i]
            svg = set_text(svg, pct_id, f"{lang['pct']}%")
            svg = set_rect_width(svg, bar_id, lang["pct"] / 100 * BAR_MAX_WIDTH)
        else:
            svg = set_text(svg, pct_id, "0%")
            svg = set_rect_width(svg, bar_id, 3)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(svg)


def main():
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN not set — using placeholder values")
        stats = {
            "repos": "—",
            "stars": "—",
            "commits": "—",
            "languages": [],
        }
    else:
        print(f"Fetching stats for {USERNAME}...")
        stats = fetch_stats()
        # Apply hardcoded overrides
        for key, val in OVERRIDES.items():
            if val is not None:
                stats[key] = val
        print(f"  Repos: {stats['repos']}")
        print(f"  Stars: {stats['stars']}")
        print(f"  Commits: {stats['commits']}")
        for lang in stats["languages"]:
            print(f"  {lang['name']}: {lang['pct']}%")

    for svg in SVG_FILES:
        if os.path.exists(svg):
            update_svg(svg, stats)
            print(f"Updated {svg}")
        else:
            print(f"Skipped {svg} (not found)")


if __name__ == "__main__":
    main()
