#!/bin/bash
set -euo pipefail

REPO="holgerkampffmeyer2/wav-to-aac-converter"
BINARY_NAME="audioconvert"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"

# Detect platform
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux)  PLATFORM="linux-amd64" ;;
    Darwin)
        case "$ARCH" in
            arm64) PLATFORM="macos-arm64" ;;
            *)     PLATFORM="macos-x86_64" ;;
        esac
        ;;
    *) echo "Error: Unsupported OS: $OS"; exit 1 ;;
esac

ARCHIVE="${BINARY_NAME}-${PLATFORM}.tar.gz"
URL="https://github.com/${REPO}/releases/latest/download/${ARCHIVE}"

echo "Installing ${BINARY_NAME} for ${PLATFORM}..."

# Download
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if command -v curl &>/dev/null; then
    curl -fsSL "$URL" -o "${TMP_DIR}/${ARCHIVE}"
elif command -v wget &>/dev/null; then
    wget -q "$URL" -O "${TMP_DIR}/${ARCHIVE}"
else
    echo "Error: curl or wget required"; exit 1
fi

# Extract
tar xzf "${TMP_DIR}/${ARCHIVE}" -C "$TMP_DIR"

# Install
if [ -w "$INSTALL_DIR" ]; then
    mv "${TMP_DIR}/${BINARY_NAME}" "${INSTALL_DIR}/${BINARY_NAME}"
else
    echo "Installing to ${INSTALL_DIR} (may need sudo)..."
    sudo mv "${TMP_DIR}/${BINARY_NAME}" "${INSTALL_DIR}/${BINARY_NAME}"
fi
chmod +x "${INSTALL_DIR}/${BINARY_NAME}"

echo "Installed: ${INSTALL_DIR}/${BINARY_NAME}"
echo "Run: ${BINARY_NAME} --version"
