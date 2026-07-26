"""
Offline verification of the DeepL integration.

The DeepL REST endpoint is not reachable from every build environment, so we
stub ONLY the HTTP layer (a fake requests.Session) and exercise the real
_RESTBackend + DeepLTranslator code: URL selection, auth header, request
fields, batching, order preservation, newline preservation and response
parsing. This validates everything except the literal network hop.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtrans.translate import DeepLTranslator, _RESTBackend, TranslatorError


class FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text
    def json(self):
        return self._payload


class FakeSession:
    """Records requests and returns canned DeepL-shaped JSON."""
    def __init__(self):
        self.posts = []
        self.gets = []
    def post(self, url, data=None, headers=None, timeout=None):
        self.posts.append({"url": url, "data": data, "headers": headers})
        # data is a list of (key, value) tuples like the real form encoding
        texts = [v for (k, v) in data if k == "text"]
        # Echo a deterministic "translation": prefix + reversed words,
        # keeping newlines so we can assert they survive.
        translations = [{"detected_source_language": "EN", "text": "〖" + t + "〗"}
                        for t in texts]
        return FakeResp(200, {"translations": translations})
    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append({"url": url, "params": params, "headers": headers})
        if params and params.get("type") == "target":
            return FakeResp(200, [{"language": "ZH", "name": "Chinese"},
                                  {"language": "JA", "name": "Japanese"}])
        return FakeResp(200, {"character_count": 1234, "character_limit": 500000})


def make_translator(key="726c9b26-xxxx:fx"):
    sess = FakeSession()
    backend = _RESTBackend(key, session=sess)
    return DeepLTranslator(key, backend=backend), sess


def test_free_key_uses_free_endpoint():
    t, sess = make_translator("abc:fx")
    t.target_languages()
    assert sess.gets[0]["url"].startswith("https://api-free.deepl.com/"), "free endpoint"
    print("✓ free key -> api-free.deepl.com")


def test_pro_key_uses_pro_endpoint():
    t, sess = make_translator("abc-no-suffix")
    t.target_languages()
    assert sess.gets[0]["url"].startswith("https://api.deepl.com/"), "pro endpoint"
    print("✓ pro key  -> api.deepl.com")


def test_auth_header_present():
    t, sess = make_translator("mykey:fx")
    t.usage()
    assert sess.gets[-1]["headers"]["Authorization"] == "DeepL-Auth-Key mykey:fx"
    print("✓ Authorization header correct")


def test_order_and_newline_and_batching():
    t, sess = make_translator()
    # 95 lines forces 3 batches at batch_size=40; include a multi-line caption.
    lines = [f"LINE {i}" for i in range(94)] + ["INJECT INTO\nTHE BEAKER"]
    out = t.translate_lines(lines, "ZH", source_lang="EN", batch_size=40)
    assert len(out) == len(lines), "count preserved"
    assert len(sess.posts) == 3, f"expected 3 batches, got {len(sess.posts)}"
    # order preserved
    assert out[0] == "〖LINE 0〗" and out[93] == "〖LINE 93〗"
    # newline preserved through the round trip
    assert out[-1] == "〖INJECT INTO\nTHE BEAKER〗", out[-1]
    # request carried the DeepL formatting fields
    keys = [k for (k, v) in sess.posts[0]["data"]]
    assert "preserve_formatting" in keys and "target_lang" in keys and "source_lang" in keys
    print("✓ batching(3) + order + newline + request fields OK")


def test_error_mapping():
    class Err403(FakeSession):
        def post(self, *a, **k):
            return FakeResp(403, text="Forbidden")
    key = "bad:fx"
    backend = _RESTBackend(key, session=Err403())
    t = DeepLTranslator(key, backend=backend)
    try:
        t.translate_lines(["x"], "ZH")
    except TranslatorError as e:
        assert "403" in str(e)
        print("✓ 403 mapped to friendly TranslatorError")
        return
    raise AssertionError("expected TranslatorError")


def test_count_mismatch_guard():
    class Short(FakeSession):
        def post(self, url, data=None, headers=None, timeout=None):
            return FakeResp(200, {"translations": [{"text": "only-one"}]})
    key = "k:fx"
    t = DeepLTranslator(key, backend=_RESTBackend(key, session=Short()))
    try:
        t.translate_lines(["a", "b", "c"], "ZH")
    except TranslatorError as e:
        assert "错位" in str(e) or "一致" in str(e)
        print("✓ count-mismatch guard prevents subtitle misalignment")
        return
    raise AssertionError("expected mismatch guard to fire")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
    print(f"\nAll {len(tests)} DeepL integration tests passed.")
