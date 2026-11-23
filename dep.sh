#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-runtime}"
if [[ "$MODE" != "runtime" && "$MODE" != "--build" ]]; then
    echo "Usage: ./dep.sh [--build]" >&2
    exit 2
fi

if [[ "$EUID" -eq 0 ]]; then
    SUDO=()
else
    command -v sudo >/dev/null 2>&1 || { echo "Install sudo or run as root." >&2; exit 1; }
    SUDO=(sudo)
fi

if command -v apt-get >/dev/null 2>&1; then
    "${SUDO[@]}" apt-get update
    PACKAGES=(python3 python3-gi gir1.2-gtk-4.0 gir1.2-webkit-6.0 gir1.2-soup-3.0
        libgtk-4-1 libwebkitgtk-6.0-4 libcurl4 curl
        gstreamer1.0-plugins-base gstreamer1.0-plugins-good
        gstreamer1.0-plugins-bad gstreamer1.0-libav)
    if [[ "$MODE" == "--build" ]]; then
        PACKAGES+=(python3-dev python3-pybind11 pybind11-dev libgtk-4-dev
            libwebkitgtk-6.0-dev libsoup-3.0-dev libcurl4-openssl-dev
            build-essential pkg-config)
    fi
    "${SUDO[@]}" apt-get install -y "${PACKAGES[@]}"
elif command -v dnf >/dev/null 2>&1; then
    PACKAGES=(python3 python3-gobject gtk4 webkitgtk6.0 libsoup3
        libcurl gstreamer1-plugins-base gstreamer1-plugins-good
        gstreamer1-plugins-bad-free gstreamer1-libav curl)
    if [[ "$MODE" == "--build" ]]; then
        PACKAGES+=(python3-devel python3-pybind11 pybind11-devel gtk4-devel
            webkitgtk6.0-devel libsoup3-devel libcurl-devel gcc-c++ make pkgconf-pkg-config)
    fi
    "${SUDO[@]}" dnf install -y "${PACKAGES[@]}"
elif command -v pacman >/dev/null 2>&1; then
    PACKAGES=(python python-gobject gtk4 webkitgtk-6.0 libsoup3 curl
        gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-libav)
    if [[ "$MODE" == "--build" ]]; then
        PACKAGES+=(python-pybind11 base-devel pkgconf)
    fi
    "${SUDO[@]}" pacman -Syu --needed "${PACKAGES[@]}"
elif command -v zypper >/dev/null 2>&1; then
    PACKAGES=(python3 python3-gobject gtk4 libwebkitgtk-6_0-4
        typelib-1_0-WebKit-6_0 libsoup-3_0-0 libcurl4
        gstreamer-plugins-base gstreamer-plugins-good curl)
    if [[ "$MODE" == "--build" ]]; then
        PACKAGES+=(python3-devel python3-pybind11 gtk4-devel
            libwebkitgtk-6_0-devel libsoup-3_0-devel libcurl-devel
            gcc-c++ make pkg-config)
    fi
    "${SUDO[@]}" zypper install -y "${PACKAGES[@]}"
else
    echo "Unsupported package manager. Install Python 3, PyGObject, GTK 4, WebKitGTK 6.0, libsoup 3, libcurl and GStreamer manually." >&2
    exit 1
fi

if [[ "$MODE" == "--build" ]]; then
    echo "Runtime and build dependencies installed."
else
    echo "Runtime dependencies installed."
fi
