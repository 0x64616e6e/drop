# drop

One-time file links for a small self-hosted server, behind nginx and Cloudflare. Built for sharing
files with a few people: no accounts, no SSO, just a link that works once (or N times) and expires.

- **drop** (server, `/usr/bin/drop`): stores files, issues links, serves the pages; nginx sends the
  bytes. Tokens are 256-bit and stored only as SHA-256.
- **share** (laptop, `/usr/bin/share`): uploads over ssh, prints links, manages them, fetches uploads,
  and runs `share watch` for desktop notifications and status-bar data.

## Links

| Link | What happens |
|---|---|
| `https://…/d/<token>` | a page with the file name/size (or "Encrypted file") and a Download button. Only the button (POST) uses the link, so chat-app previews cannot burn it |
| `https://…/d/<token>#k=…&n=…&h=…` | end-to-end encrypted file (default for `share add`): the key, name and SHA-256 are in the fragment, which browsers never send; the page decrypts with WebCrypto and verifies the checksum. The server only has ciphertext |
| `https://…/u/<token>` | one-time **upload** link: someone sends you a file (up to 95 MB by default, Cloudflare's free plan caps request bodies at 100 MB); it lands in the inbox |

Per link: `--uses N` (default 1), `--ttl 7d`, `--note NAME`, `--pass` (a generated passphrase to send
by another channel; five wrong attempts lock the link). After a download, the same IP may retry for
15 minutes (broken connections), without using another use.

## Usage

```
share add FILE [--plain] [--pass] [--qr] [--note NAME]   # upload, first link
share link FILE_ID --note NAME                           # another link (one per person)
share request --note NAME [--max-size 50M]               # upload link
share list | log | inbox | status
share fetch INBOX_ID [DEST]                              # download a received file, verify sha256
share revoke LINK_ID | --file FILE_ID ; share rm FILE_ID ; share inbox-rm ID
```

Keys of encrypted files live only in `~/.local/share/share/keys.json` (mode 600). `share link` needs
them; without that file no new links can be made for those files (existing links keep working).

`share watch` (`systemctl --user enable --now share-watch`) polls `drop status`/`drop events` every
60 s over a shared ssh connection, notifies on downloads, uploads, locked links and a certificate
expiring in under 20 days, and writes `~/.cache/share/status.json`, which `share bar` turns into one
line for polybar or Quickshell (polybar colour tags).

## Server

`drop.service` (user `drop`, sandboxed) on 127.0.0.1:8081; `drop-gc.timer` daily removes files whose
links have all been dead for 3 days, dead upload links, and events older than 90 days. The nginx site
(`/usr/share/drop/nginx-files.este.systems.conf`, installed if absent): access logs keep only the first
6 characters of a token, 5 req/s per visitor, uploads streamed, files served from an internal location.

Cloudflare Authenticated Origin Pulls: nginx always asks for Cloudflare's client certificate and logs
the result (`aop=`). After enabling AOP in Cloudflare, `drop-aop status` should show only SUCCESS;
then `drop-aop enforce` makes nginx refuse anything else (`drop-aop relax` undoes it).

## Build and test

```
python3 tests/test_drop.py        # 15 end-to-end tests against a real server on a free port
dpkg-buildpackage -us -uc -b      # drop_*.deb (server) and drop-share_*.deb (laptop); runs the tests
```

MIT licensed.
