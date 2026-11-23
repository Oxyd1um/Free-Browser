CXX = g++
CXXFLAGS = -O2 -std=c++17 -shared -fPIC
PYTHON = python3
TARGET = connections$(shell $(PYTHON)-config --extension-suffix)
PYBIND = $(shell $(PYTHON) -m pybind11 --includes)
CURL = $(shell pkg-config --cflags --libs libcurl)

all: $(TARGET)

$(TARGET): connections.cpp
	$(CXX) $(CXXFLAGS) $(PYBIND) $< -o $@ $(CURL)

clean:
	rm -f connections*.so
