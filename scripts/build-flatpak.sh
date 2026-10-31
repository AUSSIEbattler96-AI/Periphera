#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$project_dir"
command -v flatpak >/dev/null || { echo 'Install Flatpak on your distribution first.' >&2; exit 1; }
command -v flatpak-builder >/dev/null || { echo 'Install flatpak-builder first.' >&2; exit 1; }
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user --noninteractive flathub \
    org.kde.Platform//6.10 org.kde.Sdk//6.10 com.riverbankcomputing.PyQt.BaseApp//6.10
build_channel=${PERIPHERA_BUILD_CHANNEL:-testing}
case "$build_channel" in
    testing)
        python3 scripts/prepare_testing.py
        manifest=packaging/io.github.AUSSIEbattler96_AI.Periphera.Testing.json
        app_id=io.github.AUSSIEbattler96_AI.Periphera.Testing
        bundle=periphera-testing.flatpak
        ;;
    stable)
        echo 'This branch contains testing source; build the testing channel.' >&2
        exit 1
        ;;
    *) echo 'Unknown build channel' >&2; exit 1 ;;
esac
flatpak-builder --user --force-clean --repo=repo --default-branch="$build_channel" \
    --install-deps-from=flathub build "$manifest"
mkdir -p dist
flatpak build-bundle --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo \
    repo "dist/$bundle" "$app_id" "$build_channel"
sha256sum "dist/$bundle" > dist/SHA256SUMS
echo "Created dist/$bundle"

