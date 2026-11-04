"""Find Dockerfile base images that have a newer major.minor tag on Docker Hub.

Used by .github/workflows/base-images.yml, which opens an issue for each hit.
Dependabot would open a PR instead, but a base-image bump (a new Python minor)
also needs CI, requires-python and wheels for every pinned dependency to move,
so it is planned by hand rather than merged from a one-line diff.

Only tags shaped like ``<major>.<minor>[-suffix]`` (``python:3.15-slim``) are
checked; the floating tag already picks up patch and OS rebuilds. Prints one
tab-separated line per outdated image: image, current tag, newest tag, files.

    python3 .github/scripts/check_base_images.py api/Dockerfile mqtt_handler/Dockerfile
"""

import re
import sys
import urllib.error
import urllib.request

FROM = re.compile(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)", re.IGNORECASE | re.MULTILINE)
TAG = re.compile(r"^(\d+)\.(\d+)(-[a-z0-9.-]+)?$")


def tag_exists(repository: str, tag: str) -> bool:
    url = f"https://hub.docker.com/v2/repositories/{repository}/tags/{tag}"
    request = urllib.request.Request(url, headers={"User-Agent": "meshbee-base-images"})
    try:
        with urllib.request.urlopen(request, timeout=30):
            return True
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise


def newest_tag(repository: str, major: int, minor: int, suffix: str) -> tuple[int, int]:
    """Climb minors, then majors, while Docker Hub has the tag."""
    while True:
        if tag_exists(repository, f"{major}.{minor + 1}{suffix}"):
            minor += 1
        elif tag_exists(repository, f"{major + 1}.0{suffix}"):
            major, minor = major + 1, 0
        else:
            return major, minor


def main(dockerfiles: list[str]) -> None:
    images: dict[str, list[str]] = {}
    for path in dockerfiles:
        with open(path) as dockerfile:
            for image in FROM.findall(dockerfile.read()):
                images.setdefault(image, []).append(path)

    for image, paths in sorted(images.items()):
        name, _, tag = image.partition(":")
        match = TAG.match(tag)
        # Skip build-stage aliases, digests and images outside Docker Hub.
        if not match or "." in name.split("/")[0]:
            continue
        repository = name if "/" in name else f"library/{name}"
        major, minor, suffix = int(match[1]), int(match[2]), match[3] or ""
        latest = newest_tag(repository, major, minor, suffix)
        if latest != (major, minor):
            newest = f"{latest[0]}.{latest[1]}{suffix}"
            print(name, tag, newest, " ".join(paths), sep="\t")


if __name__ == "__main__":
    main(sys.argv[1:])
