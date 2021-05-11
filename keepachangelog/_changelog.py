import datetime
import re
from typing import Dict, List, Optional

from mistletoe import Document, block_token as bt, span_token as st, BaseRenderer

from keepachangelog._versioning import guess_unreleased_version


def is_release(section: bt.BlockToken) -> bool:
    """A section that indicates a release starts with a ## heading."""
    return isinstance(section, bt.Heading) and section.level == 2


def add_release(changes: Dict[str, dict], section: bt.Heading, show_unreleased: bool) -> dict:
    """Release pattern should match one of:
       "[0.0.1] - 2020-12-31"
       "[Unreleased]"
    The release number (or Unreleased) in square brackets can also be a link."""
    if len(section.children) == 1 and not show_unreleased:
        return {}
    version_token = section.children[0]
    if isinstance(version_token, st.RawText):
        version = unlink(version_token.content)
    elif isinstance(version_token, st.Link):
        version = version_token.children[0].content  # The link parsing already removes the [].

    release_date = section.children[1].content

    return changes.setdefault(
        version,
        {"version": version, "release_date": extract_date(release_date)},
    )


def unlink(value: str) -> str:
    return value.lstrip("[").rstrip("]")


def extract_date(date: str) -> str:
    if not date:
        return date

    return date.lstrip(" -(").rstrip(" )")


def is_category(section: bt.BlockToken) -> bool:
    """A section that indicates a category of changes starts with a ### heading."""
    return isinstance(section, bt.Heading) and section.level == 3


def add_category(release: dict, section: bt.Heading) -> List[str]:
    category = section.children[0].content
    return release.setdefault(category, [])


# Link pattern should match lines like: "[1.2.3]: https://github.com/user/project/releases/tag/v0.0.1"
link_pattern = re.compile(r"^\[(.*)\]: (.*)$")


def is_list(section: bt.BlockToken) -> bool:
    return isinstance(section, bt.List)


def extract_change_entry(list_entry: bt.ListItem) -> str:
    """Use mistletoe's BaseRenderer to output the text of a change entry.
    TODO: Make a smarter renderer that puts inline code and other inline items back, if wanted."""
    with BaseRenderer() as renderer:
        return renderer.render(list_entry)


def add_change_list(category: List[str], section: bt.List):
    for list_entry in section.children:
        category.append(extract_change_entry(list_entry))


def to_dict(changelog_path: str, *, show_unreleased: bool = False) -> Dict[str, dict]:
    """Parse the changelog to a dictionary using a Markdown parser."""
    changes = {}
    current_release = {}
    category = []
    with open(changelog_path) as change_log:
        parsed_changelog = Document(change_log)

    for section in parsed_changelog.children:
        if is_release(section):
            current_release = add_release(changes, section, show_unreleased)
        elif is_category(section):
            category = add_category(current_release, section)
        elif is_list(section) and current_release and category:
            add_change_list(category, section)

    return changes


def to_raw_dict(changelog_path: str) -> Dict[str, dict]:
    changes = {}
    with open(changelog_path) as change_log:
        current_release = {}
        for line in change_log:
            clean_line = line.strip(" \n")

            if is_release(clean_line):
                current_release = add_release(
                    changes, clean_line, show_unreleased=False
                )
            elif is_category(clean_line) or is_information(clean_line):
                current_release["raw"] = current_release.get("raw", "") + line

    return changes


def release(changelog_path: str) -> str:
    changelog = to_dict(changelog_path, show_unreleased=True)
    current_version, new_version = guess_unreleased_version(changelog)
    release_version(changelog_path, current_version, new_version)
    return new_version


def release_version(
    changelog_path: str, current_version: Optional[str], new_version: str
):
    unreleased_link_pattern = re.compile(r"^\[Unreleased\]: (.*)$", re.DOTALL)
    lines = []
    with open(changelog_path) as change_log:
        for line in change_log.readlines():
            # Move Unreleased section to new version
            if re.fullmatch(r"^## \[Unreleased\].*$", line, re.DOTALL):
                lines.append(line)
                lines.append("\n")
                lines.append(
                    f"## [{new_version}] - {datetime.date.today().isoformat()}\n"
                )
            # Add new version link and update Unreleased link
            elif unreleased_link_pattern.fullmatch(line):
                unreleased_compare_pattern = re.fullmatch(
                    r"^.*/(.*)\.\.\.(\w*).*$", line, re.DOTALL
                )
                # Unreleased link compare previous version to HEAD (unreleased tag)
                if unreleased_compare_pattern:
                    new_unreleased_link = line.replace(current_version, new_version)
                    lines.append(new_unreleased_link)
                    current_tag = unreleased_compare_pattern.group(1)
                    unreleased_tag = unreleased_compare_pattern.group(2)
                    new_tag = current_tag.replace(current_version, new_version)
                    lines.append(
                        line.replace(new_version, current_version)
                        .replace(unreleased_tag, new_tag)
                        .replace("Unreleased", new_version)
                    )
                # Consider that there is no way to know how to create a link to compare versions
                else:
                    lines.append(line)
                    lines.append(line.replace("Unreleased", new_version))
            else:
                lines.append(line)

    with open(changelog_path, "wt") as change_log:
        change_log.writelines(lines)
