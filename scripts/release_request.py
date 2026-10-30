"""Resolve explicit release requests without publishing on ordinary pushes."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess

REQUEST_PATH = ".github/release.json"


def resolve_release(ref, event, changed, request, version):
    result = {"enabled": False, "tag": "", "publish": False, "prerelease": True}
    if ref.startswith("refs/tags/v"):
        result.update(enabled=True, tag=ref.removeprefix("refs/tags/"))
    elif event == "push" and ref == "refs/heads/main" and REQUEST_PATH in changed:
        if not isinstance(request, dict) or set(request) != {"tag", "publish", "prerelease"}:
            raise ValueError("Release requests need exactly tag, publish and prerelease")
        if type(request["publish"]) is not bool or type(request["prerelease"]) is not bool:
            raise ValueError("Release publication flags must be booleans")
        result.update(enabled=True, **request)
    else:
        return result
    tag = result["tag"]
    if not isinstance(tag, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Use a release tag such as v0.4.0")
    if tag != "v" + version:
        raise ValueError("The requested tag must match the tested application's UI_VERSION")
    return result


def application_version():
    for node in ast.parse(Path("barracuda_gui.py").read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "UI_VERSION" for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError("UI_VERSION was not found")


def main():
    previous = subprocess.run(["git", "rev-parse", "--verify", "HEAD^"], capture_output=True)
    command = (["git", "diff", "--name-only", "HEAD^", "HEAD"] if previous.returncode == 0 else
               ["git", "ls-tree", "--name-only", "-r", "HEAD"])
    changed = subprocess.check_output(command, text=True).splitlines()
    path = Path(REQUEST_PATH)
    request = json.loads(path.read_text()) if path.exists() else None
    result = resolve_release(os.environ.get("GITHUB_REF", ""), os.environ.get("GITHUB_EVENT_NAME", ""),
                             changed, request, application_version())
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for key, value in result.items():
            output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
    print("Release request:", json.dumps(result))


if __name__ == "__main__":
    main()
