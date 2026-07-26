"""
DeepL translation integration.

Two interchangeable backends implement the same interface:

* ``_SDKBackend``  – uses the official ``deepl`` Python SDK when installed.
* ``_RESTBackend`` – talks to the DeepL REST API directly with ``requests``.
  Free keys (ending in ``:fx``) are routed to ``api-free.deepl.com``; paid
  keys to ``api.deepl.com``.

``DeepLTranslator`` prefers the SDK and transparently falls back to REST, so
the app works whether or not the SDK is present (only ``requests`` is needed).
The Free tier allows 500,000 characters/month.

``MockTranslator`` is a no-network stand-in used for offline pipeline tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


class TranslatorError(RuntimeError):
    pass


@dataclass
class LangInfo:
    code: str
    name: str


def _is_free_key(key: str) -> bool:
    return key.strip().endswith(":fx")


# --------------------------------------------------------------------------- #
# REST backend (requests)
# --------------------------------------------------------------------------- #
class _RESTBackend:
    def __init__(self, api_key: str, session=None):
        import requests

        self._requests = requests
        self.key = api_key.strip()
        self.base = ("https://api-free.deepl.com/v2" if _is_free_key(self.key)
                     else "https://api.deepl.com/v2")
        self.session = session or requests.Session()
        self.headers = {"Authorization": f"DeepL-Auth-Key {self.key}"}

    def _post(self, path, data):
        r = self.session.post(self.base + path, data=data,
                              headers=self.headers, timeout=30)
        if r.status_code == 403:
            raise TranslatorError("DeepL 拒绝访问：密钥无效或权限不足 (403).")
        if r.status_code == 456:
            raise TranslatorError("DeepL 配额已用尽 (456 quota exceeded).")
        if r.status_code >= 400:
            raise TranslatorError(f"DeepL HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def _get(self, path, params=None):
        r = self.session.get(self.base + path, params=params or {},
                             headers=self.headers, timeout=30)
        if r.status_code >= 400:
            raise TranslatorError(f"DeepL HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def target_languages(self) -> List[LangInfo]:
        data = self._get("/languages", {"type": "target"})
        return [LangInfo(d["language"], d["name"]) for d in data]

    def source_languages(self) -> List[LangInfo]:
        data = self._get("/languages", {"type": "source"})
        return [LangInfo(d["language"], d["name"]) for d in data]

    def usage(self):
        d = self._get("/usage")
        return {"count": d.get("character_count"), "limit": d.get("character_limit")}

    def translate(self, texts, target_lang, source_lang):
        data = [("text", t) for t in texts]
        data += [("target_lang", target_lang),
                 ("preserve_formatting", "1"),
                 ("split_sentences", "nonewlines")]
        if source_lang:
            data.append(("source_lang", source_lang))
        resp = self._post("/translate", data)
        return [t["text"] for t in resp["translations"]]


# --------------------------------------------------------------------------- #
# SDK backend (deepl)
# --------------------------------------------------------------------------- #
class _SDKBackend:
    def __init__(self, api_key: str):
        import deepl

        self._deepl = deepl
        self.client = deepl.Translator(api_key.strip())

    def target_languages(self) -> List[LangInfo]:
        return [LangInfo(l.code, l.name)
                for l in self.client.get_target_languages()]

    def source_languages(self) -> List[LangInfo]:
        return [LangInfo(l.code, l.name)
                for l in self.client.get_source_languages()]

    def usage(self):
        u = self.client.get_usage()
        return {"count": u.character.count if u.character else None,
                "limit": u.character.limit if u.character else None}

    def translate(self, texts, target_lang, source_lang):
        try:
            res = self.client.translate_text(
                texts, source_lang=source_lang, target_lang=target_lang,
                preserve_formatting=True, split_sentences="nonewlines")
        except self._deepl.DeepLException as e:
            raise TranslatorError(f"DeepL error: {e}") from e
        return [r.text for r in res]


# --------------------------------------------------------------------------- #
# Public translator
# --------------------------------------------------------------------------- #
class DeepLTranslator:
    def __init__(self, api_key: str, prefer: str = "auto", backend=None):
        if not api_key or not api_key.strip():
            raise TranslatorError("DeepL API key is empty.")
        self.api_key = api_key.strip()
        if backend is not None:                    # dependency injection (tests)
            self.backend = backend
            return
        if prefer in ("auto", "sdk"):
            try:
                self.backend = _SDKBackend(self.api_key)
                return
            except ImportError:
                if prefer == "sdk":
                    raise TranslatorError("deepl SDK not installed.")
            except Exception:
                if prefer == "sdk":
                    raise
        try:
            self.backend = _RESTBackend(self.api_key)
        except ImportError as e:
            raise TranslatorError(
                "Neither 'deepl' nor 'requests' is installed.") from e

    # -- metadata -----------------------------------------------------------
    def usage(self):
        return self.backend.usage()

    def target_languages(self) -> List[LangInfo]:
        return self.backend.target_languages()

    def source_languages(self) -> List[LangInfo]:
        return self.backend.source_languages()

    # -- translation --------------------------------------------------------
    def translate_lines(
        self,
        lines: List[str],
        target_lang: str,
        source_lang: Optional[str] = "EN",
        progress_cb=None,
        batch_size: int = 40,
    ) -> List[str]:
        """Translate caption strings, preserving order, count and newlines."""
        results: List[str] = []
        n = len(lines)
        for i in range(0, n, batch_size):
            chunk = lines[i : i + batch_size]
            out = self.backend.translate(chunk, target_lang, source_lang)
            if len(out) != len(chunk):
                raise TranslatorError(
                    "DeepL 返回条数与请求不一致，已中止以避免字幕错位。")
            results.extend(out)
            if progress_cb:
                progress_cb(min(1.0, (i + len(chunk)) / max(1, n)),
                            "翻译中 / Translating")
        return results


class MockTranslator:
    """Offline stand-in for tests: wraps text so the chain can be verified."""

    def __init__(self, tag: str = "ZH"):
        self.tag = tag

    def target_languages(self) -> List[LangInfo]:
        return [LangInfo("ZH", "Chinese"), LangInfo("JA", "Japanese"),
                LangInfo("DE", "German"), LangInfo("ES", "Spanish")]

    def translate_lines(self, lines, target_lang, source_lang="EN",
                        progress_cb=None, batch_size=40):
        out = [f"[{target_lang}] " + l.replace("\n", " ⏎ ") for l in lines]
        if progress_cb:
            progress_cb(1.0, "翻译中 / Translating")
        return out
