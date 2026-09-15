#!/usr/bin/env python3
"""Tests for guardian_core.claude_code — the Claude Code agent adapter.

Claude Code is one agent among possible several: its event wiring lives in
settings.json under `hooks`, and this adapter is the only place in the guardian that
knows that. Everything runs against a temporary directory standing in for ~/.claude;
the real one is never read. Run standalone:

    python3 _bin/guardian_core/claude_code_test.py
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="guardian-claude-code-")
    TMP.append(d)
    return d


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(path, mode)
    return path


class StepClock:
    def __init__(self):
        self.t = dt.datetime(2026, 9, 15, 10, 0, 0)

    def now(self):
        self.t += dt.timedelta(seconds=1)
        return self.t


class FakePaths:
    def __init__(self, missing=()):
        self.missing = set(missing)

    def exists(self, path):
        return path not in self.missing


def outcome(fn, *a, **kw):
    try:
        return fn(*a, **kw), None
    except BaseException as exc:
        return None, exc


def test_settings_store():
    print("\n== FileSettingsStore ==")
    d = tmpdir()
    path = os.path.join(d, "settings.json")
    s = CC.FileSettingsStore(path, clock=StepClock(), keep_backups=3)
    check("a missing settings file loads as empty", s.load() == {})
    backup = s.save({"hooks": {}}, "first write")
    check("saving with no previous file creates it and needs no backup",
          json.load(open(path)) == {"hooks": {}} and backup is None, backup)

    original = {"model": "opus", "note": "ñandú", "hooks": {"Stop": []}}
    write(path, json.dumps(original, ensure_ascii=False), mode=0o600)
    before = open(path, "rb").read()
    backup = s.save({"model": "opus", "note": "ñandú", "hooks": {"Stop": [{"hooks": []}]}}, "repair")
    check("an existing file is backed up before it is changed",
          backup and os.path.exists(backup) and open(backup, "rb").read() == before, backup)
    check("the backup sits next to the settings file", os.path.dirname(backup) == d)
    check("the new content is written and non-ASCII text survives",
          json.load(open(path, encoding="utf-8"))["note"] == "ñandú"
          and "ñandú" in open(path, encoding="utf-8").read())
    check("the file keeps its permissions", oct(os.stat(path).st_mode & 0o777) == oct(0o600),
          oct(os.stat(path).st_mode & 0o777))
    check("no temporary file is left behind",
          [f for f in os.listdir(d) if f.endswith(".tmp")] == [], os.listdir(d))
    for i in range(6):
        s.save({"n": i}, "loop")
    backups = [f for f in os.listdir(d) if ".bak-guardian-" in f]
    check("old guardian backups are pruned to the configured number", len(backups) == 3, backups)

    write(path, "{not json")
    _, exc = outcome(s.load)
    check("a corrupt file raises SettingsUnreadable", isinstance(exc, P.SettingsUnreadable), repr(exc))
    write(path, "[1, 2]")
    _, exc = outcome(s.load)
    check("a file that is not a JSON object raises SettingsUnreadable",
          isinstance(exc, P.SettingsUnreadable), repr(exc))


def canonical_file(d, vault_bin="__VAULT__/_bin"):
    return write(os.path.join(d, "hooks.json"), json.dumps({"hooks": {
        "Stop": [{"hooks": [
            {"type": "command", "command": "/usr/bin/python3 %s/gate_memory.py" % vault_bin, "timeout": 10},
            {"type": "command", "command": "/usr/bin/python3 %s/vault_sync.py --hook" % vault_bin,
             "async": True}]}],
        "SessionStart": [{"matcher": "startup", "hooks": [
            {"type": "command", "command": "/usr/bin/python3 %s/compass.py" % vault_bin}]}]}}))


def test_canonical():
    print("\n== CanonicalHooksFile ==")
    d = tmpdir()
    hooks = CC.CanonicalHooksFile(canonical_file(d), vault="/tmp/V", home="/tmp/H").load()
    check("canonical hooks are read and localized for this machine",
          hooks["Stop"][0]["hooks"][0]["command"] == "/usr/bin/python3 /tmp/V/_bin/gate_memory.py", hooks)


def agent(d, missing=()):
    config = os.path.join(d, "dot-claude")
    os.makedirs(config, exist_ok=True)
    settings = CC.FileSettingsStore(os.path.join(config, "settings.json"), clock=StepClock())
    canonical = CC.CanonicalHooksFile(canonical_file(d), vault="/tmp/V", home="/tmp/H")
    return CC.ClaudeCodeAgent(settings, canonical, config_dir=config, paths=FakePaths(missing)), config


def test_agent():
    print("\n== ClaudeCodeAgent ==")
    d = tmpdir()
    a, config = agent(d)
    check("the adapter is named claude-code", a.name() == "claude-code")
    check("it is present when its config directory exists", a.present())
    gone = CC.ClaudeCodeAgent(a.settings, a.canonical, config_dir=os.path.join(d, "nope"))
    check("and absent when it does not", not gone.present())

    w = a.check()
    check("with no settings file every canonical hook is a change",
          sorted(k for k, _ in w.changes)
          == ["hooks:SessionStart:compass.py", "hooks:Stop:gate_memory.py", "hooks:Stop:vault_sync.py --hook"],
          w.changes)
    check("the wiring is named after the agent and readable", w.name == "claude-code" and not w.unreadable)
    check("checking writes nothing", not os.path.exists(os.path.join(config, "settings.json")))

    settings_path = os.path.join(config, "settings.json")
    foreign = {"type": "command", "command": "/usr/local/bin/other-tool"}
    write(settings_path, json.dumps({"model": "opus", "permissions": {"allow": ["Bash"]},
                                     "hooks": {"Stop": [{"hooks": [foreign]}]}}))
    r = a.repair()
    data = json.load(open(settings_path))
    check("repair wires every canonical hook",
          a.check().changes == [], a.check().changes)
    check("repair keeps a foreign hook", foreign in data["hooks"]["Stop"][0]["hooks"], data["hooks"])
    check("repair keeps every non-hook key",
          data["model"] == "opus" and data["permissions"] == {"allow": ["Bash"]}, data)
    check("repair reports what it changed and where the backup is",
          r.name == "claude-code" and len(r.changes) == 3 and r.backup and os.path.exists(r.backup)
          and not r.errors, r)

    mtime = os.path.getmtime(settings_path)
    r = a.repair()
    check("repairing healthy wiring writes nothing",
          r.changes == [] and r.backup is None and os.path.getmtime(settings_path) == mtime, r)

    write(settings_path, "{broken")
    w = a.check()
    check("an unparseable settings file is reported unreadable with no changes",
          w.unreadable and w.changes == [], w)
    r = a.repair()
    check("and repair refuses to touch it",
          r.errors and open(settings_path).read() == "{broken", (r, open(settings_path).read()))

    d2 = tmpdir()
    a2, _ = agent(d2, missing={"/tmp/V/_bin/compass.py"})
    check("a wired script that does not exist is a missing path",
          a2.check().missing_paths == ["/tmp/V/_bin/compass.py"], a2.check().missing_paths)

    config_dir, settings_file = CC.default_locations("/home/someone")
    check("the Claude Code locations are resolved in this adapter module",
          config_dir == "/home/someone/.claude" and settings_file == "/home/someone/.claude/settings.json",
          (config_dir, settings_file))


def test_stale_hooks():
    print("\n== ClaudeCodeAgent with a stale Brain hook ==")
    d = tmpdir()
    vault = os.path.join(d, "Brain")
    for script in ("retrieve.py", "gate_memory.py"):
        write(os.path.join(vault, "_bin", script), "# stub\n")
    canonical_path = write(os.path.join(d, "hooks.json"), json.dumps({"hooks": {
        "UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": "/usr/bin/python3 __VAULT__/_bin/retrieve.py",
             "timeout": 8}]}],
        "Stop": [{"hooks": [
            {"type": "command", "command": "/usr/bin/python3 __VAULT__/_bin/gate_memory.py",
             "timeout": 10}]}]}}))
    config = os.path.join(d, "dot-claude")
    settings_path = os.path.join(config, "settings.json")
    broken = {"type": "command", "command": "/usr/bin/python3 %s/_bin/retrieve_BROKEN.py" % vault, "timeout": 8}
    foreign = {"type": "command", "command": "/usr/bin/python3 %s/not-brain/gone.py" % d}
    write(settings_path, json.dumps({"model": "opus", "hooks": {
        "UserPromptSubmit": [{"hooks": [broken]}],
        "Stop": [{"hooks": [
            foreign,
            {"type": "command", "command": "/usr/bin/python3 /old/path/Brain/_bin/gate_memory.py",
             "timeout": 10}]}]}}))
    a = CC.ClaudeCodeAgent(CC.FileSettingsStore(settings_path, clock=StepClock()),
                           CC.CanonicalHooksFile(canonical_path, vault=vault, home=d),
                           config_dir=config)

    w = a.check()
    keys = [k for k, _ in w.changes]
    check("check reports a hook running a Brain script that does not exist",
          "hooks:UserPromptSubmit:retrieve_BROKEN.py" in keys, keys)
    fs = [f for f in D.agent_findings(w) if "retrieve_BROKEN.py" in f.key]
    check("as a repairable failure", fs and fs[0].severity == "fail" and fs[0].repairable, fs)
    check("checking writes nothing", "retrieve_BROKEN.py" in open(settings_path).read())

    before = open(settings_path).read()
    r = a.repair()
    data = json.load(open(settings_path))
    commands = [h["command"] for groups in data["hooks"].values() for g in groups for h in g["hooks"]]
    check("repair removes the stale Brain hook", broken["command"] not in commands, commands)
    check("repair backs the file up first, stale hook included",
          r.backup and open(r.backup).read() == before, r.backup)
    check("the canonical hook is wired", "/usr/bin/python3 %s/_bin/retrieve.py" % vault in commands, commands)
    check("a Brain hook from a wrong vault directory is rewritten to the canonical path",
          "/usr/bin/python3 %s/_bin/gate_memory.py" % vault in commands
          and "/usr/bin/python3 /old/path/Brain/_bin/gate_memory.py" not in commands, commands)
    check("a hook that is not Brain's is kept even though its script is missing",
          foreign["command"] in commands, commands)
    check("the removal is among the reported changes",
          any("retrieve_BROKEN.py" in c for c in r.changes), r.changes)
    check("non-hook keys are kept", data.get("model") == "opus", data)

    mtime = os.path.getmtime(settings_path)
    r2 = a.repair()
    check("a second repair changes nothing",
          r2.changes == [] and r2.backup is None and os.path.getmtime(settings_path) == mtime
          and a.check().changes == [], (r2, a.check().changes))


def test_plugin_sync():
    print("\n== ClaudeCodeAgent with the plugin sync ==")
    import install_plugin as IP
    d = tmpdir()
    plugin = os.path.join(d, "vault", "integrations", "claude-code", "plugin", "brain")
    config = os.path.join(d, "dot-claude")
    state = os.path.join(d, "state")
    write(os.path.join(plugin, "skills", "fresh", "SKILL.md"), "fresh from the vault\n")
    write(os.path.join(config, "settings.json"), "{}")
    settings = CC.FileSettingsStore(os.path.join(config, "settings.json"), clock=StepClock())
    canonical = CC.CanonicalHooksFile(canonical_file(d), vault="/tmp/V", home="/tmp/H")
    a = CC.ClaudeCodeAgent(settings, canonical, config_dir=config, paths=FakePaths(),
                           plugin=IP.Syncer(plugin, config, state))
    keys = [k for k, _ in a.check().changes]
    check("a skill only the vault has is a change to install, next to the hook changes",
          "plugin:skills/fresh" in keys and any(k.startswith("hooks:") for k in keys), keys)
    r = a.repair()
    check("repair installs it into the agent's config dir",
          os.path.isfile(os.path.join(config, "skills", "fresh", "SKILL.md")), r)
    check("and still wires the hooks, leaving nothing to repair", a.check().changes == [], a.check().changes)
    check("the plugin changes are reported", any("skills/fresh" in c for c in r.changes), r.changes)

    write(os.path.join(config, "skills", "fresh", "SKILL.md"), "edited live\n")
    keys = [k for k, _ in a.check().changes]
    check("a live edit is a change to back-port", "plugin:skills/fresh" in keys, keys)
    a.repair()
    check("repair back-ports it into the vault", open(os.path.join(plugin, "skills", "fresh", "SKILL.md")).read() == "edited live\n")

    write(os.path.join(plugin, "skills", "fresh", "SKILL.md"), "vault edit\n")
    write(os.path.join(config, "skills", "fresh", "SKILL.md"), "live edit\n")
    w = a.check()
    check("a skill changed on both sides is a conflict, not a repairable change",
          [k for k, _ in w.conflicts] == ["plugin:skills/fresh"]
          and not any(k.startswith("plugin:") for k, _ in w.changes), (w.changes, w.conflicts))
    r = a.repair()
    check("repair touches neither side of a conflict",
          open(os.path.join(plugin, "skills", "fresh", "SKILL.md")).read() == "vault edit\n"
          and open(os.path.join(config, "skills", "fresh", "SKILL.md")).read() == "live edit\n")
    check("and reports it", any("conflict" in e for e in r.errors), r.errors)
    check("an agent without a plugin sync checks hooks only",
          CC.ClaudeCodeAgent(settings, canonical, config_dir=config, paths=FakePaths()).check().conflicts == [])


def main():
    global CC, P, D
    try:
        from guardian_core import claude_code as CC
        from guardian_core import domain as D
        from guardian_core import ports as P
    except Exception as exc:
        check("guardian_core.claude_code imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_settings_store, test_canonical, test_agent, test_stale_hooks, test_plugin_sync):
            try:
                t()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
