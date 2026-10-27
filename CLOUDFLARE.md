# Cloudflare access for the DNS cutover

Yes — and the right way is a **scoped API token**, not your Cloudflare
password. A token is a single string I can revoke in one click, and it can
be limited to one zone with one permission.

## 1. Create the token

1. Go to https://dash.cloudflare.com/profile/api-tokens
2. **Create Token** (top right) -> **Create Custom Token**
3. Name it `spantrail-dns`
4. **Permissions:**

   | Permission | Access | Zone |
   |---|---|---|
   | Zone | DNS | **Edit** |
   | Zone | Zone | **Read** |

5. **Zone Resources:**
   - Include -> Specific zone -> `spantrail.com`
6. **Client IP Address Filtering:** leave blank
7. **TTL:** leave blank (doesn't expire)
8. Click **Continue to summary** -> **Create Token**
9. **Copy the token now.** Cloudflare shows it once. It starts with a long
   random string.

## 2. Give it to me without putting it in the chat

Don't paste the token into this conversation. Instead, put it in a file on
your machine and I'll read it from there:

```bash
mkdir -p ~/.config/spantrail
nano ~/.config/spantrail/cf_token      # paste the token, save
chmod 600 ~/.config/spantrail/cf_token
```

Then tell me it's there. The file is gitignored, and `cf_dns.py` reads it
without printing it.

**Alternative:** if you'd rather paste it in chat, I can do the work with it
and you revoke the token immediately after. But the file route is cleaner -
the token never enters the conversation at all.

## 3. What I'll do with it

```bash
python cf_dns.py plan     # dry run: shows what would change, changes nothing
python cf_dns.py apply    # makes the changes
python cf_dns.py verify   # checks from public DNS
```

The plan is always shown first. The changes are:

| Type | Name | Content | Proxy |
|---|---|---|---|
| A | `spantrail.com` | `178.105.143.122` | DNS only (grey) |
| CNAME | `www.spantrail.com` | `spantrail.com` | DNS only (grey) |

**Grey cloud is deliberate.** With the orange cloud on, Cloudflare terminates
TLS and proxies to the origin - which breaks two things: Let's Encrypt's
http-01 challenge (Caddy on :80 never sees it) and the webhook delivery
(Stripe would reach Cloudflare, not your box, and the origin cert is
self-signed right now). DNS-only also keeps the "self-hosted on your own
server" story honest.

Any other records already on the zone are left untouched - the script lists
them before making changes.

## 4. After the DNS is live

1. I run `cutover.sh` - Caddy switches from the self-signed cert to a real
   Let's Encrypt certificate for `spantrail.com` + `www.spantrail.com`, and
   the service moves to :443
2. The Stripe webhook endpoint starts delivering (it was created already and
   Stripe has been queueing events)
3. You revoke the token: https://dash.cloudflare.com/profile/api-tokens ->
   click `spantrail-dns` -> **Revoke**

## 5. If something goes wrong

Revoke the token at any time from the same page - it takes effect
immediately, and the DNS records stay exactly as they are. Revoking the
token does not undo DNS changes; deleting the records does.

## Security notes

- The token can only touch DNS on `spantrail.com`. It cannot read your other
  zones, cannot change billing, and cannot access account settings.
- It is stored in one file on your machine, `chmod 600`, gitignored.
- `cf_dns.py` never prints it, never logs it, and never sends it anywhere
  except `api.cloudflare.com`.
- The one place it touches the network is the Cloudflare API.

## Token scope reference

For reference, here is what the token can and cannot do:

| Action | Allowed? |
|---|---|
| Read DNS records on spantrail.com | Yes |
| Create/edit/delete DNS records on spantrail.com | Yes |
| Read the zone metadata (name, id, nameservers) | Yes |
| Touch DNS on any other zone | No |
| Read account/billing/settings | No |
| Deploy workers, pages, or routes | No |
| Manage API tokens | No |
