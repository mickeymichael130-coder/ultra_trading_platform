"""
Iteration loop criteria (the "different criteria" you can plug into the loop).

Each criterion is a dict:
    id        -- short unique id (used with --phase / --only)
    phase     -- which blueprint phase it belongs to (1=quality, 2=broker
                 framework, 4=docs/manual, ...)
    title     -- human-readable name
    check     -- callable() -> (bool, message). Returning True marks the
                 criterion as met; message is shown either way.

To add a new criterion, append a dict here. The loop driver (scripts/iterate.py)
runs every criterion and prints a table so the codebase converges on the
blueprint described in docs/.
"""
import os
import re
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
SRC = os.path.join(ROOT, "src")
DOCS = os.path.join(ROOT, "docs")
CHECKLIST = os.path.join(ROOT, "BLUEPRINT_CHECKLIST.md")

FAST_TESTS = [
    "tests/test_broker_abstraction.py",
    "tests/test_broker_protocol.py",
    "tests/test_binance_client.py",
    "tests/test_config_wiring.py",
]

_CLASS_RE = re.compile(r"class (\w+)")


def _class_defined_in(src_dir, class_name):
    """True if `class <class_name>` is defined anywhere under src_dir outside
    src/core. Uses exact name matching (so `SignalEnhancer` != `Signal`)."""
    for dirpath, _dirs, files in os.walk(src_dir):
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(dirpath, f)
            if "core" in path.split(os.sep):
                continue
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped.startswith("class "):
                        continue
                    m = _CLASS_RE.match(stripped)
                    if m and m.group(1) == class_name:
                        return True, path
    return False, None


# === Criterion check functions ===

def _subclasses_basebroker():
    from src.broker import DerivClient, BinanceClient
    from src.broker.base_broker import BaseBroker
    ok = issubclass(DerivClient, BaseBroker) and issubclass(BinanceClient, BaseBroker)
    return ok, "both adapters subclass BaseBroker" if ok else "an adapter is missing BaseBroker"


def _only_core_defines_models():
    problems = []
    for name in ("Signal", "Trade", "Position", "Order", "Account",
                 "MarketTick", "Candle", "TradeSignal", "TradeExecution"):
        found, path = _class_defined_in(SRC, name)
        if found:
            problems.append(f"{name} defined in {os.path.relpath(path, ROOT)}")
    return (not problems), ("OK" if not problems else "; ".join(problems))


def _aliases_resolve():
    from src.core import domain
    import src.strategies.ema_crossover as st
    import src.execution.engine as ex
    import src.position_manager.manager as pm
    checks = {
        "TradeSignal is Signal": st.TradeSignal is domain.Signal,
        "TradeExecution is Trade": ex.TradeExecution is domain.Trade,
        "Position is core.Position": pm.Position is domain.Position,
        "Tick is MarketTick": domain.Tick is domain.MarketTick,
    }
    bad = [k for k, v in checks.items() if not v]
    return (not bad), ("OK" if not bad else "; ".join(bad))


def _factory_maps():
    from src.broker.broker_factory import get_broker_class
    from src.broker import DerivClient, BinanceClient
    ok = (get_broker_class("deriv") is DerivClient and
          get_broker_class("binance") is BinanceClient and
          get_broker_class("bogus") is DerivClient)
    return ok, "deriv/binance/unknown map correctly" if ok else "factory mapping broken"


def _fast_tests():
    cmd = [sys.executable, "-m", "pytest", "-q"] + FAST_TESTS
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                                timeout=600)
    except subprocess.TimeoutExpired:
        return False, "fast test group timed out"
    if result.returncode == 0:
        tail = result.stdout.strip().splitlines()
        last = tail[-1] if tail else ""
        return True, last
    return False, result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "fast test group failed"


def _full_tests():
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                                timeout=1200)
    except subprocess.TimeoutExpired:
        return False, "full test suite timed out (>20 min)"
    if result.returncode == 0:
        tail = result.stdout.strip().splitlines()
        last = tail[-1] if tail else ""
        return True, last
    return False, "full test suite has failures"


def _docs_manual_present():
    required = [
        "README.md", "00_Project_Overview.md", "01_System_Architecture.md",
        "02_Domain_Model.md", "03_Project_Structure.md",
        os.path.join("phases", "README.md"),
    ]
    missing = [os.path.join(DOCS, p) for p in required
               if not os.path.isfile(os.path.join(DOCS, p))]
    return (not missing), ("OK" if not missing else "missing: " + ", ".join(missing))


def _checklist_current():
    if not os.path.isfile(CHECKLIST):
        return False, "BLUEPRINT_CHECKLIST.md missing"
    today = date.today().isoformat()
    with open(CHECKLIST, "r", encoding="utf-8") as fh:
        text = fh.read()
    has_open = "## Open items for next iteration" in text
    has_today = today in text
    if has_open and has_today:
        return True, f"has today ({today}) + open items section"
    return False, f"today ({today}) or open-items section missing"


def _deploy_artifacts():
    repo_root = os.path.dirname(ROOT)
    required = [
        os.path.join(ROOT, "Dockerfile"),
        os.path.join(ROOT, "docker-compose.yml"),
        os.path.join(ROOT, ".dockerignore"),
        os.path.join(ROOT, "VERSION"),
        os.path.join(ROOT, "requirements-dev.txt"),
        os.path.join(ROOT, "deploy", "ultra.service"),
        os.path.join(ROOT, "deploy", "start.sh"),
        os.path.join(ROOT, "deploy", "start.ps1"),
        os.path.join(ROOT, "deploy", "healthcheck.ps1"),
        os.path.join(ROOT, "deploy", "healthcheck.sh"),
        os.path.join(ROOT, "deploy", "backup.ps1"),
        os.path.join(ROOT, "deploy", "backup.sh"),
        os.path.join(repo_root, ".github", "workflows", "ci.yml"),
    ]
    missing = [os.path.relpath(p, repo_root) for p in required if not os.path.isfile(p)]
    if missing:
        return False, "missing: " + ", ".join(missing)
    import yaml
    bad = []
    for f in (os.path.join(ROOT, "docker-compose.yml"),
              os.path.join(repo_root, ".github", "workflows", "ci.yml")):
        try:
            with open(f, encoding="utf-8") as fh:
                yaml.safe_load(fh)
        except Exception as exc:
            bad.append(f"{os.path.relpath(f, repo_root)}: {exc}")
    if bad:
        return False, "invalid YAML: " + "; ".join(bad)
    return True, "OK (present + YAML parses)"


def _runbook_present():
    p = os.path.join(ROOT, "DEPLOYMENT.md")
    ok = os.path.isfile(p)
    return ok, ("OK" if ok else "DEPLOYMENT.md missing")


def _no_secrets_tracked():
    repo_root = os.path.dirname(ROOT)
    env_rel = os.path.relpath(os.path.join(ROOT, ".env"), repo_root)
    tracked = subprocess.run(["git", "ls-files", env_rel], cwd=repo_root,
                             capture_output=True, text=True).stdout.strip()
    if tracked:
        return False, f"{env_rel} is tracked by git (secret risk)"
    ignored = subprocess.run(["git", "check-ignore", env_rel], cwd=repo_root,
                             capture_output=True).returncode == 0
    return ignored, ("OK (.env untracked + ignored)" if ignored
                     else f"WARN: {env_rel} untracked but not ignored")


CRITERIA = [
    {"id": "C1", "phase": 2, "title": "Adapters subclass BaseBroker",
     "check": _subclasses_basebroker},
    {"id": "C2", "phase": 2, "title": "Domain models defined only in src/core",
     "check": _only_core_defines_models},
    {"id": "C3", "phase": 2, "title": "Back-compat aliases resolve to core",
     "check": _aliases_resolve},
    {"id": "C4", "phase": 2, "title": "Broker factory maps + fallback",
     "check": _factory_maps},
    {"id": "C5", "phase": 1, "title": "Fast test group passes",
     "check": _fast_tests},
    {"id": "C6", "phase": 1, "title": "Full test suite passes (--full only)",
     "check": _full_tests, "full": True},
    {"id": "C7", "phase": 4, "title": "Docs manual present",
     "check": _docs_manual_present},
    {"id": "C8", "phase": 4, "title": "Checklist updated for current iteration",
     "check": _checklist_current},
    {"id": "C9", "phase": 17, "title": "Deploy artifacts present (Docker, VERSION, deploy/, CI)",
     "check": _deploy_artifacts},
    {"id": "C10", "phase": 17, "title": "Operator runbook present (DEPLOYMENT.md)",
     "check": _runbook_present},
    {"id": "C11", "phase": 17, "title": "No secrets tracked (.env untracked + ignored)",
     "check": _no_secrets_tracked},
]
