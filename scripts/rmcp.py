"""Call a tool of Resolve's bundled MCP server (ResolveMCP) from the command line.
Usage: python rmcp.py <tool> '<json args>'"""
import json, subprocess, sys, os
B = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Applications/ResolveMCP"
def call(name, args, timeout=120):
    p = subprocess.Popen([B], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                         env={**os.environ, "BMD_IS_MCPB": "1"})
    for m in ({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "cli", "version": "0"}}},
              {"jsonrpc": "2.0", "method": "notifications/initialized"},
              {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": args}}):
        p.stdin.write(json.dumps(m) + "\n"); p.stdin.flush()
    for line in p.stdout:
        r = json.loads(line)
        if r.get("id") == 2:
            p.kill()
            return "\n".join(c.get("text", "") for c in r.get("result", {}).get("content", [])) or json.dumps(r)
if __name__ == "__main__":
    print(call(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}))
