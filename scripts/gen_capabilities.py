#!/usr/bin/env python3
"""Generate the tier-2 capability index the gateway shadow-indexes.

A shadow capability is something this connector can DO but does not advertise as
a typed tool: it never enters `tools/list`, so it costs zero tool-surface tokens
in every session, and it is reached through the exec hatch declared in
manifest.json (`execute_sap_function`). See docs/audit/SAP2000-API-BENCHMARK.md.

Two sources, deliberately kept distinct by `verification_status`:

  verified   scripts/registry.json - 241 functions this connector has actually
             called successfully against a real SAP2000. THIS IS THE DEFAULT.
  documented API/*.md, behind --include-docs. Parsed with the connector's OWN
             doc_search parser, so the index cannot drift from what
             `search_api_docs` returns.

The doc half is OFF by default, and that is a measured decision, not caution.
All 1,898 entries score 94.3% weighted coverage but 4/8 negative controls; the
241 verified entries score 94.1% and 8/8. The extra 1,657 buy ~9 tier-2 tasks by
destroying the bundle's ability to answer "no tool for that", and the docs remain
fully reachable through the typed `search_api_docs` tool either way. See
aiconnector/docs/audit/SAP2000-API-BENCHMARK.md.

Registry wins on collision, and any name that collides with a real typed tool is
dropped - the callable one must win.

Run: python3 scripts/gen_capabilities.py
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))

OUT = ROOT / "mcp_server" / "aiconnect-capabilities.json"
EXEC_TOOL = "execute_sap_function"

# --- connector-shipped alias phrasings -------------------------------------
# Authored intent phrasings live in ONE file next to the generated index, and
# this generator is the only thing that copies them. The gateway folds them into
# its BM25 haystack only (ToolDoc::add_search_text) - never into the summary the
# model is shown, and never into the embedding.
#
# They are emitted as alias-only entries naming LISTED tools. shadow_docs skips a
# capability whose name collides with a real tool (the callable one wins), but
# merge_capability_aliases harvests its phrasings onto that tool first, so this is
# exactly where aliases pay. An older gateway simply skips them: backward compatible.
ALIAS_FILE = OUT.parent / "aiconnect_aliases.json"


def alias_entries(taken: set) -> list:
    """Alias-only entries for tools that ARE listed. No description - the real
    one arrives over tools/list."""
    if not ALIAS_FILE.is_file():
        return []
    aliases = json.loads(ALIAS_FILE.read_text(encoding="utf-8")).get("aliases", {})
    return [{"name": n, "aliases": aliases[n]}
            for n in sorted(aliases) if n not in taken and aliases[n]]

MAX_DESC = 200

# Tool names that are real, listed and callable. A shadow entry may never shadow one.
TYPED_TOOLS = {
    "connect_sap2000", "disconnect_sap2000", "get_model_info",
    "execute_sap_function", "run_sap_script", "list_scripts", "load_script",
    "search_api_docs", "list_api_categories", "query_function_registry",
    "register_verified_function", "list_registry_categories", "get_error_hints",
}


def normalise_path(syntax: str) -> str | None:
    """Doc syntax -> a dot-path execute_sap_function actually accepts.

    The docs use three notations for the same object graph:
        SapObject.SapModel.AreaElm.GetLoadGravity
        Sap2000.AreaElm.Count
        SapObject.ApplicationExit
    The executor roots on `SapModel.` or `SapObject.`, so everything is folded to
    one of those. A path that survives normalisation is one the hatch can run.
    """
    s = (syntax or "").strip().split("\n")[0].strip().rstrip("()")
    if not s or " " in s:
        return None
    if s.startswith("SapObject.SapModel."):
        return s[len("SapObject."):]
    if s.startswith("Sap2000."):
        return "SapModel." + s[len("Sap2000."):]
    if s.startswith(("SapModel.", "SapObject.")):
        return s
    if re.match(r"^[A-Za-z_][\w.]*$", s) and "." in s:
        return "SapModel." + s
    return None


def one_line(text: str) -> str:
    """First sentence, collapsed. Shadow descriptions are paid for on every
    tools.find RESULT that matches, so they stay short on purpose."""
    t = " ".join((text or "").split())
    if not t:
        return ""
    m = re.match(r"(.+?[.!?])(?:\s|$)", t)
    t = m.group(1) if m else t
    # 1,657 doc entries open with the same dead prefix. IDF makes it worthless for
    # ranking, but it is still paid for in every tools.find result that matches and
    # it dilutes the sentence embedding, so lead with the domain object instead.
    t = re.sub(r"^(?:This\s+(?:function|method)\s+)", "", t, flags=re.I)
    return (t[:1].upper() + t[1:])[:MAX_DESC].rstrip()


def from_registry() -> dict:
    reg = json.loads((ROOT / "scripts" / "registry.json").read_text())
    out = {}
    for path, e in reg.get("functions", {}).items():
        name = normalise_path(path) or path
        out[name] = {
            "name": name,
            "description": one_line(e.get("description") or e.get("parameter_notes", "")),
            "category": (e.get("category") or "").strip() or "General",
            "verification_status": "verified" if e.get("verified") else "seeded",
        }
    return out


def from_docs() -> dict:
    from doc_search import doc_index          # the connector's own parser
    doc_index._load()
    out = {}
    for s in doc_index._sections:
        name = normalise_path(s.get("syntax", ""))
        if not name:
            continue
        desc = one_line(s.get("remarks", "")) or one_line(s.get("signature", ""))
        out[name] = {
            "name": name,
            "description": desc,
            "category": s.get("category", "General"),
            "verification_status": "documented",
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--include-docs", action="store_true",
                    help="also index the ~1,657 doc-derived entries (measured net-harmful: "
                         "costs 4 of 8 negative controls for ~9 tier-2 tasks)")
    args = ap.parse_args()

    docs = from_docs() if args.include_docs else {}
    reg = from_registry()
    merged = {**docs, **reg}                  # a verified entry overrides a documented one

    dropped = [n for n in merged if n in TYPED_TOOLS]
    for n in dropped:
        del merged[n]

    caps = sorted(merged.values(), key=lambda c: c["name"])
    # `caps` stays the capability list, so every count below is unchanged by
    # aliases; the alias-only entries exist purely as a search channel.
    enriched = alias_entries({c["name"] for c in caps})
    OUT.write_text(json.dumps(
        {"exec_tool": EXEC_TOOL, "capabilities": caps + enriched}, indent=1) + "\n")
    print(f"alias-only entries for listed tools: {len(enriched)}")

    verified = sum(1 for c in caps if c["verification_status"] == "verified")
    print(f"docs {len(docs)}  registry {len(reg)}  merged {len(caps)}"
          f"  (verified {verified}, documented {len(caps) - verified})")
    if dropped:
        print(f"dropped {len(dropped)} colliding with a typed tool: {sorted(dropped)}")
    print(f"-> {OUT.relative_to(ROOT)}  {OUT.stat().st_size:,} B")


if __name__ == "__main__":
    main()
