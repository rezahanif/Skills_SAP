# Changelog

All notable changes to this project will be documented in this file.

## [1.1.1] - 2026-09-07

### Fixed
- README.md: corrected stale tool count (12 → 28) across 4 mentions, expanded the
  tools table to list all 28 registered MCP tools, and corrected `entitlement_tier`
  documentation (pro → free) to match `manifest.json`.
- `mcp_server/aioconnect.py`: updated docstring comments referencing "12 tools" to
  the current count of 28. Comment-only change, no behavior difference.

## [1.0.0] - 2026-08-24

### Added
- Typed error architecture with stable codes, hints, and recovery actions.
- AiConnect adapter layer with license gate, JWT auth, and envelope wrapping.
- MCP server with function registry, script library, and doc search.
- Process manager compatibility tests.

### Fixed
- Replaced hardcoded absolute paths in test files with relative path resolution.
- Renamed `test_typed_errors.py` to `check_typed_errors.py` to exclude from pytest.
- Replaced hardcoded `/usr/local/bin/python3` with `sys.executable` in tests.
