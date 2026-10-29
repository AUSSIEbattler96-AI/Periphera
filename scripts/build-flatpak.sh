#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$project_dir"
command -v flatpak >/dev/null || { echo 'Install Flatpak on your distribution first.' >&2; exit 1; }
command -v flatpak-builder >/dev/null || { echo 'Install flatpak-builder first.' >&2; exit 1; }
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user --noninteractive flathub \
    org.kde.Platform//6.10 org.kde.Sdk//6.10 com.riverbankcomputing.PyQt.BaseApp//6.10
flatpak-builder --user --force-clean --repo=repo --default-branch=stable \
    --install-deps-from=flathub build packaging/io.github.AUSSIEbattler96_AI.Periphera.json
mkdir -p dist
flatpak build-bundle --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo \
    repo dist/periphera.flatpak io.github.AUSSIEbattler96_AI.Periphera stable
sha256sum dist/periphera.flatpak > dist/SHA256SUMS
echo 'Created dist/periphera.flatpak'
