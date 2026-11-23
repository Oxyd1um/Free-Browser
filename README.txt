Free Browser - Network Monitor

Dependencies (Debian/Ubuntu):
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-webkit-6.0 \
    build-essential pkg-config pybind11-dev python3-pybind11 \
    libcurl4-openssl-dev

Build:
make

Run:
python3 main.py

connections.cpp performs a separate HTTP HEAD probe for the current page URL.
It does not handle or replace WebKit page/resource requests.
