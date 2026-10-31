"""Generate an independently installable testing Flatpak from the normal manifest."""
import json
from pathlib import Path

STABLE_ID = "io.github.AUSSIEbattler96_AI.Periphera"
TEST_ID = STABLE_ID + ".Testing"


def prepare(root):
    packaging = root / "packaging"
    manifest = json.loads((packaging / (STABLE_ID + ".json")).read_text())
    manifest["app-id"] = TEST_ID
    manifest["command"] = "periphera-testing"
    # Host commands are needed only for the explicit setup helper. This is a
    # broader permission than the normal build has and is documented for testers.
    manifest["finish-args"].append("--talk-name=org.freedesktop.Flatpak")
    commands = manifest["modules"][0]["build-commands"]
    commands[:] = [line.replace(STABLE_ID, TEST_ID).replace("packaging/periphera /app/bin/periphera",
                                                           "packaging/periphera-testing /app/bin/periphera-testing")
                   for line in commands]
    (packaging / (TEST_ID + ".json")).write_text(json.dumps(manifest, indent=2) + "\n")
    desktop = (packaging / (STABLE_ID + ".desktop")).read_text().replace(STABLE_ID, TEST_ID)
    desktop = desktop.replace("Name=Periphera", "Name=Periphera Testing").replace("Exec=periphera", "Exec=periphera-testing")
    desktop = desktop.replace("StartupWMClass=periphera", "StartupWMClass=periphera-testing")
    (packaging / (TEST_ID + ".desktop")).write_text(desktop)
    metadata = (packaging / (STABLE_ID + ".metainfo.xml")).read_text().replace(STABLE_ID, TEST_ID)
    metadata = metadata.replace("<name>Periphera</name>", "<name>Periphera Testing</name>")
    metadata = metadata.replace("<binary>periphera</binary>", "<binary>periphera-testing</binary>")
    metadata = metadata.replace('version="0.4.1"', 'version="0.4.2-test.1"')
    (packaging / (TEST_ID + ".metainfo.xml")).write_text(metadata)
    (packaging / (TEST_ID + ".png")).write_bytes((packaging / (STABLE_ID + ".png")).read_bytes())
    (packaging / "periphera-testing").write_text(
        '#!/bin/sh\nexport PERIPHERA_TESTING=1\nexec python3 /app/lib/periphera/barracuda.py gui "$@"\n')
    return packaging / (TEST_ID + ".json")


if __name__ == "__main__":
    print(prepare(Path(__file__).resolve().parents[1]))
