"""Faux Gemini pour les tests : rejoue des réponses scriptées à la place de `llm.generate/agenerate`."""

import copy
import json

from app.services import llm


class FakeLLM:
    """`turns` : liste de réponses {text, calls:[(nom, args)], finish, tokens_in, tokens_out},
    ou `payload` : un objet renvoyé en JSON pour toutes les requêtes (sorties structurées)."""

    def __init__(self, monkeypatch, turns=None, payload=None, finish="stop"):
        self.turns = list(turns or [])
        self.payload, self.finish = payload, finish
        self.calls: list[dict] = []
        monkeypatch.setattr(llm, "generate", self._generate)
        monkeypatch.setattr(llm, "agenerate", self._agenerate)

    def _next(self, db, contents, kw) -> llm.Result:
        self.calls.append(copy.deepcopy({"contents": contents, **kw}))
        if self.turns:
            t = self.turns.pop(0)
        else:
            t = {"text": json.dumps(self.payload if self.payload is not None else {}), "finish": self.finish}
        parts = ([{"text": t["text"]}] if t.get("text") else []) + [
            {"functionCall": {"name": n, "args": a}} for n, a in t.get("calls", [])
        ]
        return llm.Result(
            text=t.get("text", ""),
            calls=[llm.Call(n, a) for n, a in t.get("calls", [])],
            parts=parts,
            finish=t.get("finish", "stop"),
            tokens_in=t.get("tokens_in", 1000),
            tokens_out=t.get("tokens_out", 200),
        )

    def _generate(self, db, contents, **kw):
        return self._next(db, contents, kw)

    async def _agenerate(self, db, contents, **kw):
        return self._next(db, contents, kw)
