#include <pybind11/pybind11.h>
#include <curl/curl.h>
#include <memory>
#include <string>
#include <stdexcept>

namespace py = pybind11;

struct ProbeResult {
    bool ok = false;
    long status = 0;
    double latency_ms = 0.0;
    std::string error;
};

static size_t discard_data(char *, size_t size, size_t count, void *) {
    return size * count;
}

static ProbeResult probe(const std::string &url) {
    ProbeResult result;
    std::unique_ptr<CURL, decltype(&curl_easy_cleanup)> handle(
        curl_easy_init(), &curl_easy_cleanup
    );

    if (!handle) {
        result.error = "Could not create connection";
        return result;
    }

    char error[CURL_ERROR_SIZE] = {};
    curl_easy_setopt(handle.get(), CURLOPT_URL, url.c_str());
    curl_easy_setopt(handle.get(), CURLOPT_NOBODY, 1L);
    curl_easy_setopt(handle.get(), CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(handle.get(), CURLOPT_MAXREDIRS, 5L);
    curl_easy_setopt(handle.get(), CURLOPT_CONNECTTIMEOUT_MS, 2500L);
    curl_easy_setopt(handle.get(), CURLOPT_TIMEOUT_MS, 4500L);
    curl_easy_setopt(handle.get(), CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(handle.get(), CURLOPT_USERAGENT, "FreeBrowser/0.1");
    curl_easy_setopt(handle.get(), CURLOPT_WRITEFUNCTION, discard_data);
    curl_easy_setopt(handle.get(), CURLOPT_ERRORBUFFER, error);
    curl_easy_setopt(handle.get(), CURLOPT_PROTOCOLS_STR, "http,https");
    curl_easy_setopt(handle.get(), CURLOPT_REDIR_PROTOCOLS_STR, "http,https");

    double elapsed = 0.0;
    CURLcode code = curl_easy_perform(handle.get());
    curl_easy_getinfo(handle.get(), CURLINFO_TOTAL_TIME, &elapsed);
    curl_easy_getinfo(handle.get(), CURLINFO_RESPONSE_CODE, &result.status);

    result.ok = code == CURLE_OK;
    result.latency_ms = elapsed * 1000.0;
    if (!result.ok)
        result.error = error[0] ? error : curl_easy_strerror(code);

    return result;
}

PYBIND11_MODULE(connections, module) {
    if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK)
        throw std::runtime_error("Could not initialize libcurl");

    module.def("probe", [](const std::string &url) {
        ProbeResult result;
        {
            py::gil_scoped_release release;
            result = probe(url);
        }

        py::dict output;
        output["ok"] = result.ok;
        output["status"] = result.status;
        output["latency_ms"] = result.latency_ms;
        output["error"] = result.error;
        return output;
    });
}
