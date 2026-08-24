# Changelog

All notable changes to this project will be documented in this file.

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
