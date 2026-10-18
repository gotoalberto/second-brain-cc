"""Model per routine, and a repair attempt on a stronger model that also fixes the procedure.

Every scheduled routine runs on the model its job needs, a cheaper one where the strongest is not
necessary. When a run on a cheaper model fails for a reason a better model can help with, the runner
makes one more attempt on the fallback model, and that attempt also fixes the skill or the routine so
the same failure does not come back.

Front matter of a routine file (90-Meta/routines/<id>.md):

    model: haiku | sonnet | opus      the model of the first attempt (default: the template's)
    fallback_model: opus | none       the model of the repair attempt (default: opus, unless the
                                      first attempt already runs on it)

The first attempt appends `--model <model>` to the routine's agent_args (later flags win over the
agent command template's). When it fails because the run itself failed, timed out or broke its
success contract, and not for a credential, quota, network, configuration or CLI problem, the runner
makes one more attempt on the fallback model with a prompt that: says what failed, points at the
failed attempt's kept scratch directory, forbids repeating any side effect the failed attempt already
produced, asks it to fix the cause in the skill or routine (and sync the plugin), log the fix, and
then finish the job.
"""
from __future__ import annotations

import json

# The three tier names a routine may ask for. They are configuration values passed to the CLI as is.
MODELS = ("haiku", "sonnet", "opus")
DEFAULT_FALLBACK = "opus"
FIX_LOG = "90-Meta/routine-model-fallback-log.md"
# Failure kinds of routine_auth_core.domain that a better model cannot fix: the credential, the quota,
# the wire, the configuration, the CLI install. Everything else (unknown, timeout, contract_breach)
# is the run's own failure and gets the repair attempt.
NOT_A_MODEL_PROBLEM = ("auth_invalid", "usage_limit", "credit_exhausted", "network", "cli_missing",
                       "keepass_locked", "keepass_unavailable", "token_malformed", "config",
                       "no_usable_token")
# Tools the repair attempt gets on top of the routine's own: editing the procedure and syncing it.
REPAIR_TOOLS = ("Edit", "Write", "Bash(python3 ~/Brain/_bin/install_plugin.py sync:*)",
                "Bash(python3 ~/Brain/_bin/vw.py append:*)")


def _frontmatter(text: str) -> str:
    if not (text or "").startswith("---\n"):
        return ""
    end = text.find("\n---\n", 4)
    return text[4:end] if end != -1 else ""


def _field(text: str, key: str):
    for line in _frontmatter(text).splitlines():
        if line.startswith(key + ":"):
            return line[len(key) + 1:].strip().strip('"').strip("'").lower() or None
    return None


def _model_in_args(args) -> str | None:
    args = list(args or ())
    for i, a in enumerate(args):
        if a == "--model" and i + 1 < len(args):
            return args[i + 1].lower()
        if a.startswith("--model="):
            return a.split("=", 1)[1].lower()
    return None


def template_model(template) -> str | None:
    """The model the agent command template pins with --model, or None when it pins none."""
    if not template:
        return None
    words = template if isinstance(template, (list, tuple)) else str(template).split()
    return _model_in_args(words)


def routine_model(text: str, args=(), default: str | None = None) -> tuple[str | None, str | None]:
    """(model, fallback) for a routine.

    `model` None means the template's own model, `default` (None when the template pins none).
    `fallback` None means no repair attempt: turned off, or the first attempt already runs on it.
    """
    model = _field(text, "model") or _model_in_args(args)
    if model and model not in MODELS:
        model = None
    fb = _field(text, "fallback_model")
    if fb in ("none", "no", "off"):
        fallback = None
    elif fb in MODELS:
        fallback = fb
    else:
        fallback = DEFAULT_FALLBACK
    effective = model or default
    if fallback and fallback == effective:
        fallback = None
    return model, fallback


def with_model(args, model: str | None) -> tuple:
    """The routine's args with `--model <model>` appended (dropping any earlier --model in them)."""
    out, skip = [], False
    for a in args or ():
        if skip:
            skip = False
            continue
        if a == "--model":
            skip = True
            continue
        if a.startswith("--model="):
            continue
        out.append(a)
    if model:
        out += ["--model", model]
    return tuple(out)


def fallback_eligible(kind: str, rc: int) -> bool:
    """Can a better model help with this failure?"""
    return rc != 0 and (kind or "unknown") not in NOT_A_MODEL_PROBLEM


def repair_args(args, prev_scratch: str | None) -> tuple:
    """Args for the repair attempt: the repair tools added to the allowlist, and the failed
    attempt's scratch directory readable."""
    out = list(args or ())
    for i, a in enumerate(out):
        if a in ("--allowedTools", "--allowed-tools") and i + 1 < len(out):
            have = out[i + 1]
            listed = set(t.strip() for t in have.split(","))
            extra = [t for t in REPAIR_TOOLS if t not in listed]
            out[i + 1] = ",".join([have] + extra) if extra else have
            break
    else:
        out += ["--allowedTools", ",".join(REPAIR_TOOLS)]
    if prev_scratch:
        out += ["--add-dir", prev_scratch]
    return tuple(out)


def _tail(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return "[...]\n" + s[-n:]


def _result_text(stdout: str) -> str:
    """The CLI runs with --output-format json: its `result` field is the agent's last answer."""
    try:
        data = json.loads(stdout)
        if isinstance(data, dict) and isinstance(data.get("result"), str):
            return data["result"]
    except (ValueError, TypeError):
        pass
    return stdout or ""


def repair_text(text: str, routine_id: str, first_model: str, fallback: str, summary: str,
                stdout: str, stderr: str, prev_scratch: str | None) -> str:
    """The routine file with a repair preamble put in front of its body (front matter kept)."""
    fm_end = text.find("\n---\n", 4) if text.startswith("---\n") else -1
    head, body = (text[:fm_end + 5], text[fm_end + 5:]) if fm_end != -1 else ("", text)
    out = _tail(_result_text(stdout), 4000)
    err = _tail(stderr, 1500)
    scratch = (f"Its scratch directory was kept and you can read it: `{prev_scratch}` (drafts, specs, logs "
               "it wrote).") if prev_scratch else "Its scratch directory was not kept."
    pre = f"""## REPAIR RUN ON {fallback.upper()} (read this first)

The scheduled run of `{routine_id}` on **{first_model}** failed just now: {summary or "no summary"}.
{scratch}

Its last answer (tail):
```
{out or "(empty)"}
```
Its stderr (tail):
```
{err or "(empty)"}
```

Do this, in order:

1. **Never repeat a side effect.** Before doing anything, check what the failed attempt already did:
   the routine's log note, the places it publishes to, the sent mail. Whatever already went out stays
   as it is: do not post, send, create or move it again. The routine's own guards apply as written.
2. **Find the cause.** Decide whether the failure came from the procedure or the model (an unclear
   or missing step, a wrong command, a rule the model broke, a check it skipped) or from outside
   (a site down, a login lost, an empty data source). For an outside cause, fix nothing: report it
   and end with the routine's failure line, as the routine says.
3. **Fix the procedure** when the cause is the procedure or the model: edit the skill the routine
   uses in `~/Brain/integrations/claude-code/plugin/brain/skills/<skill>/` (never the installed copies
   in ~/.claude/skills, which the sync overwrites) or the routine file
   `~/Brain/90-Meta/routines/{routine_id}.md`, with a precise rule or step that makes a cheaper model
   get it right next time. Keep the change minimal and specific; never weaken a safety rule. Then run
   `python3 ~/Brain/_bin/install_plugin.py sync`. This is the only exception to "never write inside
   ~/Brain" in this run.
4. **Log the fix**: write a short entry to a file in your scratch directory and append it with
   `python3 ~/Brain/_bin/vw.py append {FIX_LOG} < <file>`: routine, first model, what failed, the
   cause, the file and change you made (or "outside cause, no change").
5. **Finish the job**: run the procedure below as the routine asks, from the point the failed
   attempt left it, and end with the routine's own final line.

---

"""
    return head + pre + body.lstrip("\n")
