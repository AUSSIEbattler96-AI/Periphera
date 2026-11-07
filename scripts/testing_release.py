"""Publish only an explicit, version-matched prerelease from its testing branch."""
import json
import os
from pathlib import Path
import re
import subprocess

REQUEST_PATH = ".github/testing-release.json"


def resolve(ref, event, changed, request, version):
    result = {"enabled": False, "tag": ""}
    if event != "push" or not ref.startswith("refs/heads/testing/") or REQUEST_PATH not in changed:
        return result
    if not isinstance(request, dict) or set(request) != {"branch", "tag"}:
        raise ValueError("Testing release requests need exactly branch and tag")
    if ref != "refs/heads/" + request["branch"]:
        raise ValueError("The requested release must come from the named testing branch")
    tag = request["tag"]
    if not isinstance(tag, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+-test\.[1-9][0-9]*", tag):
        raise ValueError("Testing releases require a version such as v0.4.2-test.2")
    if tag != "v" + version:
        raise ValueError("The tag must match the application's tested UI_VERSION")
    return {"enabled": True, "tag": tag}


def main():
    from release_request import application_version
    changed = subprocess.check_output(["git", "diff", "--name-only", "HEAD^", "HEAD"], text=True).splitlines()
    path = Path(REQUEST_PATH)
    result = resolve(os.environ.get("GITHUB_REF", ""), os.environ.get("GITHUB_EVENT_NAME", ""),
                     changed, json.loads(path.read_text()) if path.exists() else None, application_version())
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for key, value in result.items():
            output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
