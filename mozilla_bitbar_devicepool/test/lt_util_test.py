import mozilla_bitbar_devicepool.lambdatest.util as util
from mozilla_bitbar_devicepool.lambdatest.util import (
    array_key_search,
    get_device_from_job_labels,
    get_pool_from_job_labels,
    shorten_worker_type,
)


def test_shorten_worker_type_removes_prefix():
    assert shorten_worker_type("gecko-t-lambda-android") == "android"
    assert shorten_worker_type("gecko-t-lambda-foo-bar") == "foo-bar"


def test_shorten_worker_type_no_prefix():
    assert shorten_worker_type("android") == "android"
    assert shorten_worker_type("lambda-android") == "lambda-android"


def test_array_key_search_found():
    arr = ["foo", "bar", "baz", "prefix-match", "other"]
    assert array_key_search("prefix", arr) == "prefix-match"
    assert array_key_search("ba", arr) == "bar"


def test_array_key_search_not_found():
    arr = ["foo", "bar", "baz"]
    assert array_key_search("qux", arr) is None
    assert array_key_search("", arr) == "foo"  # empty prefix matches first


def test_array_key_search_empty_array():
    assert array_key_search("foo", []) is None


def test_get_device_from_job_labels():
    assert get_device_from_job_labels(["tcdp", "a55-perf", "R5CXC1PW7CR"]) == "R5CXC1PW7CR"
    assert get_device_from_job_labels(["tcdp", "a55-perf", "R5CXC1PW7CRZZ333A8"]) == "R5CXC1PW7CRZZ333A8"
    assert get_device_from_job_labels(["tcdp", "unit-test", "perf-test"]) is None
    assert get_device_from_job_labels([]) is None
    assert get_device_from_job_labels(["tcdp"]) is None
    assert get_device_from_job_labels(["device-123", "tcdp"]) == "device-123"


def test_get_device_from_job_labels_with_known_devices():
    known_devices = {"RZCY107MCLV"}

    assert get_device_from_job_labels(["tcdp", "test-1", "RZCY107MCLV"], known_devices) == "RZCY107MCLV"
    assert get_device_from_job_labels(["tcdp", "test-1", "unknown-device"], known_devices) is None


def test_get_pool_from_job_labels():
    pools = {"a55-perf", "test-1"}

    assert get_pool_from_job_labels(["tcdp", "test-1", "RZCY107MCLV"], pools) == "test-1"
    assert get_pool_from_job_labels(["tcdp", "a55-perf", "RZCY107MCLV"], pools) == "a55-perf"
    assert get_pool_from_job_labels(["tcdp", "RZCY107MCLV"], pools) == "unknown"


# test string_list_to_list()
def test_string_list_to_list():
    assert util.string_list_to_list('["tcdp","a55-perf","R5CXC1PW7CR"]') == ["tcdp", "a55-perf", "R5CXC1PW7CR"]
    assert util.string_list_to_list('["device-123", "unit-test"]') == ["device-123", "unit-test"]
    assert util.string_list_to_list("[]") == []
    assert util.string_list_to_list("") == []
    assert util.string_list_to_list(None) == []
    assert util.string_list_to_list('["single-item"]') == ["single-item"]
