"""
Rock-Solid Pure Python MCP Engine (Zero-Dependency FastMCP replacement).
100% Python Standard Library: sys, json, inspect, typing.
Guarantees 0 ModuleNotFoundError on any clean Python 3.8+ system.
"""

import sys
import os
import json
import inspect
import typing
import traceback
from typing import Any, Callable, Dict, List, Optional

def _py_type_to_json_schema(t: Any) -> Dict[str, Any]:
    """Convert Python type hints to JSON Schema types."""
    origin = typing.get_origin(t)
    args = typing.get_args(t)

    # Handle Optional[X] / Union[X, None]
    if origin is typing.Union:
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            return _py_type_to_json_schema(non_none_args[0])

    if t in (str, Optional[str]):
        return {"type": "string"}
    elif t in (int, Optional[int]):
        return {"type": "integer"}
    elif t in (float, Optional[float]):
        return {"type": "number"}
    elif t in (bool, Optional[bool]):
        return {"type": "boolean"}
    elif t in (list, List) or origin in (list, List):
        return {"type": "array"}
    elif t in (dict, Dict) or origin in (dict, Dict):
        return {"type": "object"}
    return {"type": "string"}

class ToolDefinition:
    def __init__(self, fn: Callable, name: Optional[str] = None, description: Optional[str] = None):
        self.fn = fn
        self.name = name or fn.__name__
        self.description = (description or inspect.getdoc(fn) or f"Execute {self.name}").strip()
        
        # Build JSON Schema from inspect
        sig = inspect.signature(fn)
        type_hints = typing.get_type_hints(fn) if hasattr(typing, 'get_type_hints') else {}
        
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ('self', 'cls'):
                continue
            param_type = type_hints.get(param_name, str)
            schema_type = _py_type_to_json_schema(param_type)
            
            # Param docstring or name
            properties[param_name] = schema_type
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        self.input_schema = {
            "type": "object",
            "properties": properties,
            "required": required
        }

class PromptDefinition:
    def __init__(self, fn: Callable, name: Optional[str] = None, description: Optional[str] = None):
        self.fn = fn
        self.name = name or fn.__name__
        self.description = (description or inspect.getdoc(fn) or f"Prompt template for {self.name}").strip()
        
        sig = inspect.signature(fn)
        self.arguments = []
        for param_name, param in sig.parameters.items():
            if param_name in ('self', 'cls'):
                continue
            self.arguments.append({
                "name": param_name,
                "description": f"Argument {param_name}",
                "required": param.default is inspect.Parameter.empty
            })

class FastMCP:
    """Zero-dependency, rock-solid FastMCP implementation."""
    def __init__(self, name: str = "mcp-server", instructions: str = "", **kwargs):
        self.name = name
        self.instructions = instructions
        self.tools: Dict[str, ToolDefinition] = {}
        self.prompts: Dict[str, PromptDefinition] = {}

    def tool(self, name: Optional[str] = None, description: Optional[str] = None):
        def decorator(fn: Callable):
            tool_def = ToolDefinition(fn, name=name, description=description)
            self.tools[tool_def.name] = tool_def
            return fn
        return decorator

    def prompt(self, name: Optional[str] = None, description: Optional[str] = None):
        def decorator(fn: Callable):
            prompt_def = PromptDefinition(fn, name=name, description=description)
            self.prompts[prompt_def.name] = prompt_def
            return fn
        return decorator

    def run(self, transport: str = "stdio"):
        """Run standard MCP JSON-RPC 2.0 stdio loop."""
        sys.stderr.write(f"[{self.name}] Pure-Python MCP server running on stdio.\n")
        sys.stderr.flush()

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                req = json.loads(line)
                req_id = req.get("id")
                method = req.get("method")
                params = req.get("params", {})

                if method == "initialize":
                    resp = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "serverInfo": {
                                "name": self.name,
                                "version": "1.0.0"
                            },
                            "capabilities": {
                                "tools": {},
                                "prompts": {}
                            }
                        }
                    }
                    self._send(resp)

                elif method == "tools/list":
                    tools_list = []
                    for t in self.tools.values():
                        tools_list.append({
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": t.input_schema
                        })
                    resp = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"tools": tools_list}
                    }
                    self._send(resp)

                elif method == "prompts/list":
                    prompts_list = []
                    for p in self.prompts.values():
                        prompts_list.append({
                            "name": p.name,
                            "description": p.description,
                            "arguments": p.arguments
                        })
                    resp = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"prompts": prompts_list}
                    }
                    self._send(resp)

                elif method == "prompts/get":
                    prompt_name = params.get("name")
                    prompt_args = params.get("arguments", {})
                    p_def = self.prompts.get(prompt_name)
                    if not p_def:
                        self._send_error(req_id, -32601, f"Prompt {prompt_name} not found")
                        continue
                    
                    try:
                        result = p_def.fn(**prompt_args)
                        messages = result if isinstance(result, list) else [{"role": "user", "content": {"type": "text", "text": str(result)}}]
                        self._send({
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "description": p_def.description,
                                "messages": messages
                            }
                        })
                    except Exception as e:
                        self._send_error(req_id, -32000, f"Prompt error: {str(e)}")

                elif method == "tools/call":
                    tool_name = params.get("name")
                    tool_args = params.get("arguments", {})
                    tool_def = self.tools.get(tool_name)

                    if not tool_def:
                        self._send_error(req_id, -32601, f"Tool {tool_name} not found")
                        continue

                    try:
                        res = tool_def.fn(**tool_args)
                        # Format text content
                        text_res = json.dumps(res, default=str) if not isinstance(res, str) else res
                        resp = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": text_res
                                    }
                                ]
                            }
                        }
                        self._send(resp)
                    except Exception as e:
                        tb = traceback.format_exc()
                        sys.stderr.write(f"Tool {tool_name} error: {tb}\n")
                        sys.stderr.flush()
                        self._send({
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "isError": True,
                                "content": [
                                    {
                                        "type": "text",
                                        "text": json.dumps({
                                            "status": "fail",
                                            "error": {
                                                "code": "TOOL_EXECUTION_ERROR",
                                                "message": str(e)
                                            }
                                        })
                                    }
                                ]
                            }
                        })

                elif method == "notifications/initialized":
                    pass # Acknowledgement

                else:
                    self._send_error(req_id, -32601, f"Method {method} not found")

            except Exception as ex:
                sys.stderr.write(f"MCP Loop error: {ex}\n")
                sys.stderr.flush()

    def _send(self, data: dict):
        sys.stdout.write(json.dumps(data) + "\n")
        sys.stdout.flush()

    def _send_error(self, req_id: Any, code: int, message: str):
        self._send({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": code,
                "message": message
            }
        })
