"""
Fetches GitHub stats for dmriding and updates the SVG templates.
Designed to run via GitHub Actions with GITHUB_TOKEN env var.
"""

import os
import json
import urllib.request
import urllib.error
from xml.etree import ElementTree as ET

USERNAME = "dmriding"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
API_URL = "https://api.github.com/graphql"
SVG_FILES = ["dark_mode.svg", "light_mode.svg"]
BAR_MAX_WIDTH = 150


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
    query = """
    query($login: String!) {
        user(login: $login) {
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
            contributionsCollection {
                totalCommitContributions
                restrictedContributionsCount
            }
        }
    }
    """
    data = graphql(query, {"login": USERNAME})
    user = data["data"]["user"]
    repos = user["repositories"]

    # Count stars
    total_stars = sum(r["stargazerCount"] for r in repos["nodes"])

    # Count commits
    contribs = user["contributionsCollection"]
    total_commits = (
        contribs["totalCommitContributions"]
        + contribs["restrictedContributionsCount"]
    )

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
    """Update an SVG file with fresh stats."""
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    tree = ET.parse(filepath)
    root = tree.getroot()
    ns = {"svg": "http://www.w3.org/2000/svg"}

    def set_text(element_id: str, value: str) -> None:
        el = root.find(f".//svg:text[@id='{element_id}']", ns)
        if el is not None:
            el.text = value

    def set_rect_width(element_id: str, width: float) -> None:
        el = root.find(f".//svg:rect[@id='{element_id}']", ns)
        if el is not None:
            el.set("width", str(max(3, int(width))))

    # Update stats text
    set_text("repos_data", str(stats["repos"]))
    set_text("stars_data", str(stats["stars"]))
    set_text("commits_data", str(stats["commits"]))

    # Update language bars and percentages
    lang_ids = [
        ("rust_bar", "rust_pct"),
        ("python_bar", "python_pct"),
        ("other_bar", "other_pct"),
    ]
    for i, (bar_id, pct_id) in enumerate(lang_ids):
        if i < len(stats["languages"]):
            lang = stats["languages"][i]
            set_text(pct_id, f"{lang['pct']}%")
            set_rect_width(bar_id, lang["pct"] / 100 * BAR_MAX_WIDTH)
        else:
            set_text(pct_id, "0%")
            set_rect_width(bar_id, 3)

    tree.write(filepath, encoding="unicode", xml_declaration=False)


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
