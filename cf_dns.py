#!/usr/bin/env python3
"""Manage the spantrail.com DNS records in Cloudflare.

The API token is read from a file or an environment variable. It is never
printed, never logged, and never written to the repo.

Usage:
    python cf_dns.py list
    python cf_dns.py plan            # show what would change, change nothing
    python cf_dns.py apply           # make the changes
    python cf_dns.py verify          # re-check from public DNS

The token needs these permissions (Cloudflare -> My Profile -> API Tokens ->
Create Custom Token):
    Zone -> DNS -> Edit     (for spantrail.com only)
    Zone -> Zone -> Read    (to find the zone id)
"""
import json
import os
import sys
import urllib.request
import urllib.error

API = "https://api.cloudflare.com/client/v4"
ZONE_NAME = "spantrail.com"
VPS_IP = "178.105.143.122"
TOKEN_FILE = os.path.expanduser("~/.config/spantrail/cf_token")

# The records we want to exist. proxied=False (grey cloud) is required for
# Let's Encrypt's http-01 challenge to reach Caddy on :80.
DESIRED = [
    {"type": "A", "name": ZONE_NAME, "content": VPS_IP,
     "ttl": 300, "proxied": False},
    {"type": "CNAME", "name": "www." + ZONE_NAME, "content": ZONE_NAME,
     "ttl": 300, "proxied": False},
]


def get_token():
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if token:
        return token
    if os.path.isfile(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    die("no token found.\n"
        "  Set CLOUDFLARE_API_TOKEN, or write it to:\n"
        "    %s\n"
        "  (chmod 600)" % TOKEN_FILE)


def die(msg, code=1):
    print("\nERROR: %s\n" % msg, file=sys.stderr)
    sys.exit(code)


def api(method, path, token, body=None):
    url = API + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read().decode())
            errs = j.get("errors", [])
            msg = "; ".join(
                "%s (code %s)" % (x.get("message"), x.get("code")) for x in errs
            ) or e.reason
        except Exception:
            msg = e.reason
        die("Cloudflare API error on %s %s: %s" % (method, path, msg))
    except Exception as e:
        die("could not reach the Cloudflare API: %s" % e)


def verify_token(token):
    r = api("GET", "/user/tokens/verify", token)
    if not r.get("success"):
        die("token verification failed")
    res = r.get("result", {})
    print("  token status : %s" % res.get("status"))
    return res


def get_zone(token):
    r = api("GET", "/zones?name=%s" % ZONE_NAME, token)
    if not r.get("success"):
        die("could not read the zone")
    zones = r.get("result", [])
    if not zones:
        die("zone %s not found. The token needs Zone:Read on this zone." % ZONE_NAME)
    z = zones[0]
    print("  zone         : %s (%s)" % (z.get("name"), z.get("id")))
    print("  zone status  : %s" % z.get("status"))
    print("  nameservers  : %s" % ", ".join(z.get("name_servers", [])))
    return z


def list_records(token, zone_id):
    r = api("GET", "/zones/%s/dns_records?per_page=200" % zone_id, token)
    if not r.get("success"):
        die("could not list DNS records")
    return r.get("result", [])


def show_records(records):
    if not records:
        print("  (no DNS records exist for this zone)")
        return
    print("  %-6s %-24s %-26s %-8s %s" % ("TYPE", "NAME", "CONTENT", "TTL", "PROXY"))
    for rec in records:
        print("  %-6s %-24s %-26s %-8s %s" % (
            rec.get("type"), rec.get("name"), str(rec.get("content"))[:25],
            rec.get("ttl"), "proxied" if rec.get("proxied") else "DNS only"))


def plan(token, zone_id, records):
    print("\n=== CURRENT ===")
    show_records(records)

    existing = {}
    for rec in records:
        existing[(rec.get("type"), rec.get("name"))] = rec

    print("\n=== PLAN ===")
    changes = []
    for want in DESIRED:
        key = (want["type"], want["name"])
        cur = existing.get(key)
        if not cur:
            changes.append(("create", want, None))
            print("  CREATE  %-6s %-24s -> %s (ttl %s, %s)" % (
                want["type"], want["name"], want["content"], want["ttl"],
                "proxied" if want["proxied"] else "DNS only"))
        elif (cur.get("content") != want["content"]
              or cur.get("proxied") != want["proxied"]
              or cur.get("ttl") != want["ttl"]):
            changes.append(("update", want, cur))
            print("  UPDATE  %-6s %-24s" % (want["type"], want["name"]))
            print("            content : %s -> %s" % (cur.get("content"), want["content"]))
            print("            proxied : %s -> %s" % (cur.get("proxied"), want["proxied"]))
            print("            ttl     : %s -> %s" % (cur.get("ttl"), want["ttl"]))
        else:
            print("  OK      %-6s %-24s %s" % (want["type"], want["name"], want["content"]))

    # Anything else on the zone, e.g. the old rowok.dev endpoint. Leave alone.
    extra = [r for r in records
             if (r.get("type"), r.get("name")) not in
             {(d["type"], d["name"]) for d in DESIRED}]
    if extra:
        print("\n  (leaving %d other record(s) untouched)" % len(extra))
        for r in extra:
            print("    %-6s %-24s %s" % (r.get("type"), r.get("name"),
                                         str(r.get("content"))[:40]))
    return changes


def apply(token, zone_id, changes):
    if not changes:
        print("\n  nothing to do - the records are already correct.")
        return
    print("\n=== APPLYING ===")
    for action, want, cur in changes:
        if action == "create":
            body = dict(want)
            body["zone_id"] = zone_id
            r = api("POST", "/zones/%s/dns_records" % zone_id, token, body)
            print("  CREATED %-6s %-24s -> %s" % (
                want["type"], want["name"], r.get("result", {}).get("id", "?")))
        else:
            rec_id = cur.get("id")
            body = {
                "type": want["type"],
                "name": want["name"],
                "content": want["content"],
                "ttl": want["ttl"],
                "proxied": want["proxied"],
            }
            r = api("PUT", "/zones/%s/dns_records/%s" % (zone_id, rec_id), token, body)
            print("  UPDATED %-6s %-24s -> %s" % (
                want["type"], want["name"], r.get("result", {}).get("id", "?")))


def public_verify():
    print("\n=== PUBLIC DNS CHECK ===")
    import subprocess
    import re
    for name, rtype in [(ZONE_NAME, "A"), ("www." + ZONE_NAME, "A"),
                         (ZONE_NAME, "NS")]:
        got = "(none)"
        try:
            out = subprocess.run(
                ["nslookup", "-type=%s" % rtype, name, "1.1.1.1"],
                capture_output=True, text=True, timeout=20)
            text = (out.stdout or "") + (out.stderr or "")
            if "can't find" in text.lower() or "NONEXISTENT" in text:
                got = "(NXDOMAIN - not delegated)"
            elif rtype == "NS":
                # NS answers are hostnames, not IPs.
                names = re.findall(r"([A-Za-z0-9.-]+\.ns[A-Za-z0-9.-]*\.[A-Za-z]{2,})", text)
                if not names:
                    names = re.findall(r"(ns\d*\.[A-Za-z0-9.-]+\.[A-Za-z]{2,})", text)
                got = ", ".join(dict.fromkeys(names)) if names else "(none)"
            else:
                ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
                ips = [ip for ip in ips
                       if ip != "1.1.1.1" and not ip.startswith("127.")]
                if ips:
                    got = ", ".join(dict.fromkeys(ips))
        except Exception as e:
            got = "(lookup failed: %s)" % e
        print("  %-24s %-4s -> %s" % (name, rtype, got))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"
    print("SpanTrail - Cloudflare DNS (%s)" % cmd)
    print("=" * 62)

    token = get_token()

    if cmd == "verify":
        public_verify()
        return

    print("\n=== TOKEN ===")
    verify_token(token)
    zone = get_zone(token)
    zone_id = zone["id"]
    records = list_records(token, zone_id)

    if cmd == "list":
        print("\n=== RECORDS ===")
        show_records(records)
        return

    changes = plan(token, zone_id, records)

    if cmd == "plan":
        print("\n  (dry run - nothing was changed. Use 'apply' to make these changes.)")
        return

    if cmd == "apply":
        apply(token, zone_id, changes)
        print("\n=== RESULT ===")
        show_records(list_records(token, zone_id))
        public_verify()
        return

    die("unknown command: %s" % cmd)


if __name__ == "__main__":
    main()
