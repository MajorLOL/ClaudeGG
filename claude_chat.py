"""Claude in the web interface: a chat on the right side of the page (web.py).

Claude talks with the owner of the bot about what it does and can look at it: the state of the bot, the log, the
phone screen and the code on this Pi. It never changes anything on the Pi. A change to the code is made as a pull
request on GitHub, from a branch of its own (in the user's fork when the user is not the maker), and handed in at
the repository of the maker - who decides whether it goes in.

Only the Python standard library: the Claude API (https://api.anthropic.com/v1/messages) and the GitHub REST API
are called with urllib. The API key and the GitHub token are kept on the Pi (~/.config/gamebot, readable only by
the user) and never go to the browser."""
import base64
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
GITHUB = "https://api.github.com"
MODELS = ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"]
DEFAULT_MODEL = "claude-sonnet-5-5"
EFFORTS = ["low", "medium", "high", "xhigh", "max"]   # output_config.effort; '' = the model's own default
MAX_TOKENS_FOR = {"": 16000, "low": 12000, "medium": 16000, "high": 32000, "xhigh": 64000, "max": 64000}
MAKER_FALLBACK = "MajorLOL/pokemon-go-automation"     # the repository of the maker, when git does not say it
MAX_ROUNDS = 25                # tool rounds in one answer
KEEP_MESSAGES = 60             # of the conversation for the API (older ones are dropped)
SHOWN_KEEP = 200               # lines shown in the chat
READ_LINES = 400               # at most this many lines per read_file
READ_CHARS = 45000
LOG_READ_BYTES = 3000000
TEXT_FILES = (".py", ".md", ".sh", ".service", ".json", ".txt", ".cfg", ".toml", ".yml", ".yaml")

CONF_DIR = os.path.expanduser("~/.config/gamebot")
KEY_FILE = os.path.join(CONF_DIR, "anthropic_api_key")
GH_FILE = os.path.join(CONF_DIR, "github_token")
SETTINGS_FILE = os.path.expanduser("~/claude_chat.json")
HISTORY_FILE = os.path.expanduser("~/claude_chat_history.json")   # (the one chat of before the projects)
STORE_DIR = os.path.expanduser("~/claude_chat")                     # projects.json and chats/<id>.json
NOTES_MAX = 12000             # characters of project knowledge


# ---------- secrets and settings ----------
def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _write_secret(path, value):
    os.makedirs(CONF_DIR, mode=0o700, exist_ok=True)
    if not value:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value.strip())
    os.chmod(path, 0o600)


def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(d):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(d, f, indent=1)


# ---------- HTTP ----------
class ApiError(Exception):
    def __init__(self, code, text):
        super().__init__(f"{code}: {text}")
        self.code, self.text = code, text


def _http(method, url, headers, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="ignore")
        try:
            j = json.loads(text)
            text = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else j.get("message", text)
        except ValueError:
            pass
        raise ApiError(e.code, str(text)[:400])
    except urllib.error.URLError as e:
        raise ApiError(0, f"no connection ({e.reason})")


def gh(method, path, token, body=None):
    return _http(method, GITHUB + path, {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                                         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "gamebot-claude-chat",
                                         "Content-Type": "application/json"}, body, timeout=60)


def call_claude(key, model, system, messages, tools, effort=""):
    """One request to the Messages API. effort: low ... max (output_config.effort), '' for the model's default.
    Thinking counts toward max_tokens, so a higher effort gets more room."""
    body = {"model": model, "max_tokens": MAX_TOKENS_FOR.get(effort, 16000), "system": system, "messages": messages,
            "tools": tools}
    if effort in EFFORTS:
        body["output_config"] = {"effort": effort}
    return _http("POST", API_URL, {"x-api-key": key, "anthropic-version": API_VERSION,
                                   "content-type": "application/json"}, body, timeout=900)


# ---------- the repository ----------
def parse_github(url):
    """'owner/repo' of a GitHub remote URL, or ''."""
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", (url or "").strip())
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def repo_files(repo_dir):
    """The text files of the repository (the ones git knows; without git: the files in the folder)."""
    try:
        out = subprocess.run(["git", "-C", repo_dir, "ls-files"], capture_output=True, timeout=10).stdout.decode()
        files = [f for f in out.splitlines() if f]
    except Exception:  # noqa: BLE001
        files = []
    if not files:
        files = []
        for root, dirs, names in os.walk(repo_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "debug")]
            for n in names:
                files.append(os.path.relpath(os.path.join(root, n), repo_dir))
    return sorted(f for f in files if f.endswith(TEXT_FILES) and not os.path.basename(f).startswith("."))


def safe_path(repo_dir, path, files=None):
    """The full path of a repository file, or None for anything outside it or not one of its text files."""
    path = (path or "").strip().lstrip("/")
    if not path or ".." in path.split("/") or path not in (files if files is not None else repo_files(repo_dir)):
        return None
    return os.path.join(repo_dir, path)


def git_version(repo_dir):
    try:
        return subprocess.run(["git", "-C", repo_dir, "log", "-1", "--format=%h %cd", "--date=short"],
                              capture_output=True, timeout=10).stdout.decode().strip()
    except Exception:  # noqa: BLE001
        return ""


def apply_change(text, old, new, path):
    """`text` with `old` replaced by `new` (old must be there exactly once). Raises ValueError."""
    n = text.count(old)
    if n != 1:
        raise ValueError(f"{path}: the old text is there {n} times, it must be there exactly once"
                         + (" (read the file again: the newest version on GitHub can differ from the Pi)" if n == 0 else
                            " (take more lines around it)"))
    return text.replace(old, new, 1)


def open_pull_request(token, maker, title, description, changes, model="", now=None):
    """Make a branch with the changes and hand in a pull request at the maker's repository.
    changes: [{path, old_text, new_text}] (old_text '' = a new file). The changes are made on the newest version
    of the maker's main branch. Returns (url, number, branch). Raises ValueError / ApiError."""
    if not changes:
        raise ValueError("no changes")
    me = gh("GET", "/user", token)["login"]
    up = gh("GET", f"/repos/{maker}", token)
    base_branch = up.get("default_branch") or "main"
    owner, name = maker.split("/", 1)
    if me.lower() == owner.lower():
        head_repo = maker
    else:                                             # a fork of the user's own; the pull request goes to the maker
        try:
            fork = gh("GET", f"/repos/{me}/{name}", token)
            ok = (fork.get("source") or fork.get("parent") or {}).get("full_name", "").lower() == maker.lower()
        except ApiError as e:
            if e.code != 404:
                raise
            ok = False
        if not ok:
            fork = gh("POST", f"/repos/{maker}/forks", token, {"default_branch_only": True})
            for _ in range(30):
                try:
                    gh("GET", f"/repos/{fork['full_name']}/git/ref/heads/{base_branch}", token)
                    break
                except ApiError:
                    time.sleep(2)
        head_repo = fork["full_name"]
        try:
            gh("POST", f"/repos/{head_repo}/merge-upstream", token, {"branch": base_branch})
        except ApiError:
            pass                                      # (the commit is made on the maker's newest version anyway)
    base_sha = gh("GET", f"/repos/{maker}/git/ref/heads/{base_branch}", token)["object"]["sha"]
    base_tree = gh("GET", f"/repos/{maker}/git/commits/{base_sha}", token)["tree"]["sha"]
    files = {}
    for ch in changes:
        path = str(ch.get("path", "")).strip().lstrip("/")
        if not path or ".." in path.split("/"):
            raise ValueError(f"not a file of the repository: {path!r}")
        old, new = str(ch.get("old_text", "")), str(ch.get("new_text", ""))
        if path not in files:
            try:
                info = gh("GET", f"/repos/{maker}/contents/{path}?ref={base_sha}", token)
                raw = info.get("content") or ""
                if not raw and info.get("sha"):       # (bigger than 1 MB: as a blob)
                    raw = gh("GET", f"/repos/{maker}/git/blobs/{info['sha']}", token).get("content", "")
                files[path] = base64.b64decode(raw).decode("utf-8")
            except ApiError as e:
                if e.code != 404:
                    raise
                files[path] = None
        if files[path] is None:
            if old:
                raise ValueError(f"{path} does not exist on GitHub (a new file has an empty old_text)")
            files[path] = new
        elif not old:
            raise ValueError(f"{path} exists already: give the old text to replace")
        else:
            files[path] = apply_change(files[path], old, new, path)
    for path, text in files.items():
        if path.endswith(".py"):
            try:
                compile(text, path, "exec")
            except SyntaxError as e:
                raise ValueError(f"{path} would not run any more: {e.msg} on line {e.lineno}")
    tree = gh("POST", f"/repos/{head_repo}/git/trees", token,
              {"base_tree": base_tree, "tree": [{"path": p, "mode": "100644", "type": "blob", "content": t}
                                                for p, t in files.items()]})
    message = title.strip() + "\n\n" + description.strip() + "\n\nMade with Claude in the web interface of the bot."
    commit = gh("POST", f"/repos/{head_repo}/git/commits", token,
                {"message": message, "tree": tree["sha"], "parents": [base_sha]})
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "change"
    branch = f"claude/{slug}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}"
    gh("POST", f"/repos/{head_repo}/git/refs", token, {"ref": "refs/heads/" + branch, "sha": commit["sha"]})
    body = (description.strip() + "\n\n---\nMade with Claude" + (f" ({model})" if model else "")
            + f" in the web interface of the bot of {me}. Files: " + ", ".join(f"`{p}`" for p in files) + ".")
    pr = gh("POST", f"/repos/{maker}/pulls", token,
            {"title": title.strip(), "body": body, "head": (branch if head_repo == maker else f"{me}:{branch}"),
             "base": base_branch, "maintainer_can_modify": True})
    return pr["html_url"], pr["number"], branch


# ---------- the tools Claude can use ----------
TOOLS = [
    {"name": "get_status", "description": "The state of the bot now: service running or not, today's counters, "
     "the battles of today, the last test, the settings (switches).", "input_schema": {"type": "object", "properties": {}}},
    {"name": "read_log", "description": "The end of the bot's log (~/spin.log), newest last. Every line starts with its "
     "date and time. Use 'contains' to keep only lines with that text (case does not matter).",
     "input_schema": {"type": "object", "properties": {
         "lines": {"type": "integer", "description": "how many lines (at most 600), default 150"},
         "contains": {"type": "string", "description": "only lines with this text"}}}},
    {"name": "screenshot", "description": "The phone screen right now (the live picture of the web interface).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_files", "description": "The files of the bot's code (the repository on this Pi).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "read_file", "description": f"Lines of a file of the code on this Pi, with line numbers (at most "
     f"{READ_LINES} lines per call).", "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}, "start": {"type": "integer", "description": "first line, default 1"},
         "end": {"type": "integer", "description": "last line"}}, "required": ["path"]}},
    {"name": "search_code", "description": "Search the code for a regular expression (Python syntax). Returns "
     "file:line: text, at most 100 hits.", "input_schema": {"type": "object", "properties": {
         "pattern": {"type": "string"}, "path": {"type": "string", "description": "only this file"}},
         "required": ["pattern"]}},
    {"name": "save_note", "description": "Keep a short note in the knowledge of this project, which every chat of the "
     "project gets: a finding or a decision worth remembering later (not what is in the code or the log anyway).",
     "input_schema": {"type": "object", "properties": {"text": {"type": "string", "description": "one or two sentences"}},
                      "required": ["text"]}},
    {"name": "create_pull_request", "description": "Propose a change of the code: it is made on a branch of its own "
     "and handed in as a pull request at the maker's repository on GitHub, who decides whether it goes in. Nothing "
     "on this Pi changes. Each change replaces old_text (exactly as in the file, appearing once) by new_text; an "
     "empty old_text makes a new file with new_text. Python files are checked to still compile.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string", "description": "short, in English, what the change does"},
         "description": {"type": "string", "description": "in English: the problem, what was seen, what changes, "
                         "how to test it (which test of Test one part)"},
         "changes": {"type": "array", "items": {"type": "object", "properties": {
             "path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
             "required": ["path", "old_text", "new_text"]}}},
         "required": ["title", "description", "changes"]}},
]

SYSTEM = """You are Claude, built into the web interface of a Pokémon GO bot. The bot runs on a Raspberry Pi and plays \
the game on an Android phone over ADB: it spins PokéStops, catches Pokémon, opens and sends gifts, fights GO Battle \
League battles and Team GO Rocket, cleans up the bag and claims GO Pass rewards. The web interface shows the phone \
screen live, has switches for every part and a "Test one part" list to run one part on its own from a known screen \
(tests: {chapters}).

You help the owner of this bot: explain what the bot did and why (read the log and look at the screen), find the cause \
of a problem in the code, and propose fixes.

Rules:
- You never change anything on the Pi. A change to the code is only ever made with create_pull_request: it goes on a \
branch of its own and is handed in as a pull request at the maker's repository ({maker}), where the maker reviews it. \
Give the user the link it returns.
- Read the code involved before you propose a change; keep a change small and about one thing, in the style of the \
code (English names, comments and log lines in plain words). Say in the description how to test it, with a test of \
"Test one part" when one fits.
- Never put trainer names (player names seen on the screen or in the log), screenshots, log lines with player names, \
API keys or tokens into a pull request.
- Things on the phone you do not do yourself: tell the user what to press or which test to run.
- Answer in the language the user writes in, short and to the point. Code, log lines and pull requests stay in English.

The code on this Pi: version {version}. Now: {now}.

This chat belongs to the project "{project}". Keep what is worth remembering for later chats of this project with save_note (a finding, a decision of the user) - not things that are in the code or the log anyway.{instructions}{notes}"""


def _new_id():
    return time.strftime("%Y%m%d%H%M%S") + "-" + base64.b32encode(os.urandom(5)).decode().lower()


class Chat:
    """The chats with Claude, in projects: a project has instructions and knowledge (notes) that every chat of it
    gets; a chat is one conversation. One answer at a time, in a thread; the page asks for the state."""

    def __init__(self, repo_dir, status_fn=None, log_file=None, shot_fn=None, write_log=None, chapters=None):
        self.repo_dir = repo_dir
        self.status_fn = status_fn or (lambda: {})
        self.log_file = log_file or os.path.expanduser("~/spin.log")
        self.shot_fn = shot_fn or (lambda: None)
        self.write_log = write_log or (lambda m: None)
        self.chapters = chapters or []
        self.lock = threading.Lock()
        self.busy, self.progress, self.error, self.cancel = False, "", "", False
        self.projects = self._load_projects()
        self.cur = None
        st = load_settings()
        (self._open(st.get("chat")) or self._open_newest(st.get("project") or self.projects[0]["id"])
         or self._start(self.projects[0]["id"]))

    # --- the current chat ---
    @property
    def messages(self):
        return self.cur["messages"]

    @messages.setter
    def messages(self, v):
        self.cur["messages"] = v

    @property
    def shown(self):
        return self.cur["shown"]

    @shown.setter
    def shown(self, v):
        self.cur["shown"] = v

    @property
    def tokens(self):
        return self.cur["tokens"]

    # --- storing ---
    @staticmethod
    def _chats_dir():
        return os.path.join(STORE_DIR, "chats")

    def _load_projects(self):
        try:
            with open(os.path.join(STORE_DIR, "projects.json")) as f:
                projects = [p for p in json.load(f) if isinstance(p, dict) and p.get("id")]
        except (OSError, ValueError, TypeError):
            projects = []
        if not projects:
            projects = [{"id": _new_id(), "name": "Pokémon GO bot", "instructions": "", "notes": ""}]
            self.projects = projects
            self._save_projects()
            try:                                  # the chat of before the projects becomes its first chat
                with open(HISTORY_FILE) as f:
                    old = json.load(f)
                if old.get("shown"):
                    chat = self._blank(projects[0]["id"])
                    chat.update(messages=old.get("messages", []), shown=old.get("shown", []),
                                tokens=old.get("tokens", chat["tokens"]))
                    chat["title"] = self._title_of(chat)
                    self._write(chat)
            except (OSError, ValueError, AttributeError):
                pass
        return projects

    def _save_projects(self):
        os.makedirs(STORE_DIR, exist_ok=True)
        with open(os.path.join(STORE_DIR, "projects.json"), "w") as f:
            json.dump(self.projects, f, indent=1, ensure_ascii=False)

    def _project(self, pid=None):
        pid = pid or (self.cur or {}).get("project")
        return next((p for p in self.projects if p["id"] == pid), self.projects[0])

    @staticmethod
    def _blank(pid):
        now = time.strftime("%Y-%m-%d %H:%M")
        return {"id": _new_id(), "project": pid, "title": "", "messages": [], "shown": [], "tokens": {"in": 0, "out": 0},
                "created": now, "updated": now, "ts": time.time()}

    @staticmethod
    def _title_of(chat):
        first = next((m["text"] for m in chat["shown"] if m["role"] == "user"), "")
        first = " ".join(first.split())
        return (first[:60] + ("..." if len(first) > 60 else "")) or "New chat"

    def _write(self, chat):
        os.makedirs(self._chats_dir(), exist_ok=True)
        with open(os.path.join(self._chats_dir(), chat["id"] + ".json"), "w") as f:
            json.dump(chat, f, ensure_ascii=False)

    def _read(self, cid):
        if not cid or not re.fullmatch(r"[0-9a-z-]+", str(cid)):
            return None
        try:
            with open(os.path.join(self._chats_dir(), cid + ".json")) as f:
                chat = json.load(f)
            return chat if isinstance(chat, dict) and chat.get("id") == cid else None
        except (OSError, ValueError):
            return None

    def chats(self, pid=None):
        """[{id, title, updated}] of a project, newest first."""
        pid = pid or self._project()["id"]
        out = []
        try:
            names = os.listdir(self._chats_dir())
        except OSError:
            names = []
        for n in names:
            chat = self._read(n[:-5]) if n.endswith(".json") else None
            if chat and chat.get("project") == pid and (chat.get("shown") or chat["id"] == (self.cur or {}).get("id")):
                out.append({"id": chat["id"], "title": chat.get("title") or "New chat", "updated": chat.get("updated", ""),
                            "ts": chat.get("ts", 0)})
        cur = self.cur or {}
        if cur.get("project") == pid and not any(c["id"] == cur.get("id") for c in out):
            out.append({"id": cur["id"], "title": cur.get("title") or "New chat", "updated": cur.get("updated", ""),
                        "ts": cur.get("ts", time.time())})
        return sorted(out, key=lambda c: (c["ts"], c["updated"]), reverse=True)

    def _remember(self):
        st = load_settings()
        st.update(chat=self.cur["id"], project=self.cur["project"])
        save_settings(st)

    def _open(self, cid):
        chat = self._read(cid)
        if not chat or not any(p["id"] == chat.get("project") for p in self.projects):
            return False
        chat.setdefault("tokens", {"in": 0, "out": 0})
        self.cur = chat
        self._remember()
        return True

    def _open_newest(self, pid):
        if not pid or not any(p["id"] == pid for p in self.projects):
            return False
        lst = self.chats(pid)
        return self._open(lst[0]["id"]) if lst else False

    def _start(self, pid):
        self.cur = self._blank(pid)
        self._remember()
        return True

    def _save(self):
        self.cur["updated"], self.cur["ts"] = time.strftime("%Y-%m-%d %H:%M"), time.time()
        if not self.cur.get("title") or self.cur["title"] == "New chat":
            self.cur["title"] = self._title_of(self.cur)
        try:
            self._write(self.cur)
        except OSError:
            pass

    def _show(self, role, text, **extra):
        self.shown.append({"role": role, "text": text, "t": time.strftime("%H:%M"), **extra})
        self.shown = self.shown[-SHOWN_KEEP:]

    @staticmethod
    def _trim(messages, pictures=False):
        """The last KEEP_MESSAGES, starting with a question of the user (not with the answer of a tool); with
        pictures=False also without pictures (at the end of an answer: they were for that one answer)."""
        out = messages[-KEEP_MESSAGES:]
        while out and not (out[0]["role"] == "user" and (isinstance(out[0]["content"], str) or not any(
                b.get("type") == "tool_result" for b in out[0]["content"]))):
            out = out[1:]
        for m in ([] if pictures else out):
            if isinstance(m["content"], list):
                for b in m["content"]:
                    if b.get("type") == "tool_result" and isinstance(b.get("content"), list):
                        b["content"] = [c if c.get("type") != "image" else {"type": "text", "text": "[the picture of then]"}
                                        for c in b["content"]]
        return out

    # --- chats and projects from the page ---
    def open_chat(self, cid):
        with self.lock:
            return not self.busy and self._open(cid)

    def new(self, pid=None):
        with self.lock:
            if self.busy:
                return False
            if self.cur and not self.cur["shown"] and (not pid or pid == self.cur["project"]):
                return True                       # (an empty new chat is there already)
            self.error, self.progress = "", ""
            return self._start(self._project(pid)["id"])

    def delete_chat(self, cid):
        with self.lock:
            if self.busy or not self._read(cid):
                return False
            try:
                os.remove(os.path.join(self._chats_dir(), cid + ".json"))
            except OSError:
                return False
            if self.cur and self.cur["id"] == cid:
                pid = self.cur["project"]
                self._open_newest(pid) or self._start(pid)
            return True

    def open_project(self, pid):
        with self.lock:
            if self.busy or not any(p["id"] == pid for p in self.projects):
                return False
            return self._open_newest(pid) or self._start(pid)

    def save_project(self, d):
        """Make (no id) or change a project: name, instructions, notes. Returns the project or None."""
        name = " ".join(str(d.get("name") or "").split())[:60]
        with self.lock:
            p = next((p for p in self.projects if p["id"] == d.get("id")), None) if d.get("id") else None
            if p is None:
                if not name:
                    return None
                p = {"id": _new_id(), "name": name, "instructions": "", "notes": ""}
                self.projects.append(p)
            if name:
                p["name"] = name
            for k in ("instructions", "notes"):
                if k in d:
                    p[k] = str(d[k] or "")[:NOTES_MAX]
            self._save_projects()
            if not d.get("id") and not self.busy:
                self._start(p["id"])
            return p

    def delete_project(self, pid):
        """A project and its chats go; the last project stays."""
        with self.lock:
            if self.busy or len(self.projects) < 2 or not any(p["id"] == pid for p in self.projects):
                return False
            for c in self.chats(pid):
                try:
                    os.remove(os.path.join(self._chats_dir(), c["id"] + ".json"))
                except OSError:
                    pass
            self.projects = [p for p in self.projects if p["id"] != pid]
            self._save_projects()
            if self.cur["project"] == pid:
                self._open_newest(self.projects[0]["id"]) or self._start(self.projects[0]["id"])
            return True

    # --- settings ---
    def maker(self):
        """The maker's repository: where the code on this Pi comes from (the source of a fork), else the default."""
        st = load_settings()
        if st.get("maker"):
            return st["maker"]
        try:
            url = subprocess.run(["git", "-C", self.repo_dir, "remote", "get-url", "origin"],
                                 capture_output=True, timeout=10).stdout.decode()
        except Exception:  # noqa: BLE001
            url = ""
        return parse_github(url) or MAKER_FALLBACK

    def state(self):
        st, p = load_settings(), self._project()
        return {"has_key": bool(_read(KEY_FILE)), "has_github": bool(_read(GH_FILE)), "github_user": st.get("github_user", ""),
                "model": st.get("model", DEFAULT_MODEL), "models": MODELS, "effort": st.get("effort", ""),
                "efforts": EFFORTS, "maker": self.maker(), "busy": self.busy, "progress": self.progress,
                "error": self.error, "messages": self.shown[-SHOWN_KEEP:], "tokens": self.tokens,
                "chat": {"id": self.cur["id"], "title": self.cur.get("title") or "New chat"},
                "project": p, "projects": [{"id": q["id"], "name": q["name"]} for q in self.projects],
                "chats": self.chats(p["id"])}

    def set_settings(self, d):
        """api_key / github_token: '' leaves it as it is, '-' removes it. Returns (ok, message)."""
        st = load_settings()
        if d.get("model") in MODELS:
            st["model"] = d["model"]
        if "effort" in d and (d["effort"] in EFFORTS or d["effort"] == ""):
            st["effort"] = d["effort"]
        key = str(d.get("api_key") or "").strip()
        if key:
            _write_secret(KEY_FILE, "" if key == "-" else key)
        tok = str(d.get("github_token") or "").strip()
        msg = "saved"
        if tok == "-":
            _write_secret(GH_FILE, "")
            st.pop("github_user", None)
        elif tok:
            try:
                st["github_user"] = gh("GET", "/user", tok)["login"]
            except ApiError as e:
                save_settings(st)
                return False, f"GitHub did not accept the token ({e.text})"
            _write_secret(GH_FILE, tok)
            msg = f"saved - GitHub user {st['github_user']}"
        save_settings(st)
        return True, msg

    def stop(self):
        self.cancel = True

    # --- asking ---
    def send(self, text):
        text = (text or "").strip()
        if not text:
            return False, "empty"
        with self.lock:
            if self.busy:
                return False, "Claude is still answering"
            if not _read(KEY_FILE):
                return False, "no API key: add it under Settings of the chat"
            self.busy, self.cancel, self.error, self.progress = True, False, "", "Thinking"
            self._show("user", text)
            self.messages.append({"role": "user", "content": text})
            self._save()
        threading.Thread(target=self._answer, daemon=True, name="claude-chat").start()
        return True, "ok"

    def system_prompt(self):
        p = self._project()
        instructions = ("\n\nInstructions of the project (from the user):\n" + p["instructions"].strip()) if p.get("instructions", "").strip() else ""
        notes = ("\n\nKnowledge of the project (notes kept earlier):\n" + p["notes"].strip()) if p.get("notes", "").strip() else ""
        return SYSTEM.format(chapters=", ".join(self.chapters) or "-", maker=self.maker(),
                             version=git_version(self.repo_dir) or "unknown", now=time.strftime("%Y-%m-%d %H:%M"),
                             project=p["name"], instructions=instructions, notes=notes)

    def _answer(self):
        try:
            key, st = _read(KEY_FILE), load_settings()
            model, effort = st.get("model", DEFAULT_MODEL), st.get("effort", "")
            system = self.system_prompt()
            for _ in range(MAX_ROUNDS):
                if self.cancel:
                    self._show("note", "Stopped.")
                    break
                self.progress = "Thinking"
                res = self._call(key, model, system, effort)
                self.tokens["in"] += (res.get("usage") or {}).get("input_tokens", 0)
                self.tokens["out"] += (res.get("usage") or {}).get("output_tokens", 0)
                content = res.get("content") or []
                self.messages.append({"role": "assistant", "content": content})
                for b in content:
                    if b.get("type") == "text" and b.get("text", "").strip():
                        self._show("assistant", b["text"].strip())
                self._save()
                if res.get("stop_reason") == "max_tokens":
                    self._show("note", "The answer was cut off (too long for this effort level). Ask to go on.")
                uses = [b for b in content if b.get("type") == "tool_use"]
                if res.get("stop_reason") != "tool_use" or not uses:
                    break
                results = []
                for b in uses:
                    if self.cancel:
                        out, err = "stopped by the user", True
                    else:
                        out, err = self.run_tool(b["name"], b.get("input") or {}, model)
                    results.append({"type": "tool_result", "tool_use_id": b["id"], "content": out, "is_error": err})
                self.messages.append({"role": "user", "content": results})
                self._save()
            else:
                self._show("note", f"Stopped after {MAX_ROUNDS} steps: ask again to go on.")
        except ApiError as e:
            self.error = ("The API key is not accepted." if e.code == 401 else
                          f"Claude could not answer: {e.text}" if e.code else f"Claude could not be reached: {e.text}")
            self._show("note", self.error)
        except Exception as e:  # noqa: BLE001
            self.error = f"Something went wrong: {e}"
            self._show("note", self.error)
        finally:
            self.messages = self._trim(self.messages)
            self.busy, self.progress = False, ""
            self._save()

    def _call(self, key, model, system, effort=""):
        for attempt in range(3):
            try:
                return call_claude(key, model, system, self._trim(self.messages, pictures=True), TOOLS, effort)
            except ApiError as e:
                if e.code in (429, 500, 502, 503, 529) and attempt < 2:
                    self.progress = "Busy at Anthropic - trying again"
                    time.sleep(8 * (attempt + 1))
                    continue
                raise

    def run_tool(self, name, inp, model=""):
        """(content for the tool_result, is_error)."""
        try:
            if name == "get_status":
                self.progress = "Looking at the state of the bot"
                st = dict(self.status_fn() or {})
                for k in ("labels", "apps", "w", "h"):
                    st.pop(k, None)
                return json.dumps(st, ensure_ascii=False)[:20000], False
            if name == "read_log":
                n = max(1, min(600, int(inp.get("lines") or 150)))
                want = str(inp.get("contains") or "").lower()
                self.progress = "Reading the log" + (f" ({want})" if want else "")
                with open(self.log_file, "rb") as f:
                    f.seek(0, 2)
                    f.seek(max(f.tell() - LOG_READ_BYTES, 0))
                    lines = f.read().decode(errors="ignore").splitlines()
                if want:
                    lines = [l for l in lines if want in l.lower()]
                text = "\n".join(lines[-n:])
                return (text[-60000:] or "(no such lines)"), False
            if name == "screenshot":
                self.progress = "Looking at the phone screen"
                jpg = self.shot_fn()
                if not jpg:
                    return "no picture of the phone right now", True
                self._show("note", "Looked at the phone screen.")
                return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": base64.b64encode(jpg).decode()}}], False
            if name == "list_files":
                return "\n".join(repo_files(self.repo_dir)), False
            if name == "read_file":
                full = safe_path(self.repo_dir, inp.get("path"))
                if not full:
                    return f"not a file of the code: {inp.get('path')!r} (see list_files)", True
                with open(full, errors="ignore") as f:
                    lines = f.read().splitlines()
                a = max(1, int(inp.get("start") or 1))
                b = min(len(lines), int(inp.get("end") or a + READ_LINES - 1), a + READ_LINES - 1)
                self.progress = f"Reading {inp['path']}"
                out = "\n".join(f"{i}: {lines[i - 1]}" for i in range(a, b + 1))[:READ_CHARS]
                return f"{inp['path']} ({len(lines)} lines), lines {a}-{b}:\n{out}", False
            if name == "search_code":
                try:
                    rx = re.compile(inp.get("pattern") or "")
                except re.error as e:
                    return f"not a valid pattern: {e}", True
                known = repo_files(self.repo_dir)
                files = [inp["path"]] if inp.get("path") else known
                self.progress = f"Searching the code for {inp.get('pattern')}"
                hits = []
                for p in files:
                    full = safe_path(self.repo_dir, p, known)
                    if not full:
                        continue
                    with open(full, errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if rx.search(line):
                                hits.append(f"{p}:{i}: {line.rstrip()[:200]}")
                                if len(hits) >= 100:
                                    return "\n".join(hits) + "\n(more hits: search narrower)", False
                return "\n".join(hits) or "nothing found", False
            if name == "save_note":
                text = " ".join(str(inp.get("text") or "").split())[:500]
                if not text:
                    return "empty note", True
                p = self._project()
                p["notes"] = ((p.get("notes") or "").rstrip() + "\n- " + text).strip()[-NOTES_MAX:]
                self._save_projects()
                self._show("note", "Kept in the project knowledge: " + text)
                return "kept", False
            if name == "create_pull_request":
                tok = _read(GH_FILE)
                if not tok:
                    return ("no GitHub token on this Pi: the user can add one under the gear of the chat (a token "
                            "with the right to make pull requests). Tell the user the change instead."), True
                self.progress = "Making the pull request"
                url, number, branch = open_pull_request(tok, self.maker(), str(inp.get("title", "")),
                                                        str(inp.get("description", "")), inp.get("changes") or [], model)
                self._show("note", f"Pull request #{number} handed in: {url}", url=url)
                self.write_log(f"claude: pull request #{number} handed in at {self.maker()}: {url}")
                return f"pull request #{number} made: {url} (branch {branch})", False
            return f"unknown tool {name}", True
        except ApiError as e:
            return f"GitHub said {e.code}: {e.text}", True
        except (OSError, ValueError, KeyError, TypeError) as e:
            return f"failed: {e}", True
