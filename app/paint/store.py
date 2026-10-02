"""Saved paint layouts, in one JSON file:

  {"current": {device id: pattern}, "saved": {name: {device id: pattern}}}

"current" is the layout being painted, kept between sessions. Patterns are
Pattern.to_json() dicts; devices that aren't connected keep theirs untouched.
"""

import json


class LayoutStore:
    def __init__(self, path):
        self.path = path
        self.current, self.saved = {}, {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data.get("current"), dict):
                self.current = data["current"]
            if isinstance(data.get("saved"), dict):
                self.saved = {k: v for k, v in data["saved"].items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            pass

    def names(self):
        return sorted(self.saved, key=str.lower)

    def write(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"current": self.current, "saved": self.saved}),
                           encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass
