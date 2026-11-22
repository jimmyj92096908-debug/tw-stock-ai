# TWSE 5-year capacity: owner-local encrypted archive (not a Neon migration)

**Status: local implementation, no full-history export, Neon deletion, LINE edit or model release.**

This tool creates a *private local* AES-256-GCM archive from a **read-only**
Neon snapshot. It is intended for an owner-controlled Windows PC or
private workstation, **not GitHub Actions** and never a public repository.
An archive and successful verification alone do NOT authorize removal of
original Neon historical rows or indexes. Work item: Issue #176.

## Before export

- Choose a local folder **outside the public Git checkout**, on a filesystem
  controlled by the owner. Have enough free local disk space. Treat exported
  stock data and database credentials as private.
- Keep a 64-character hex AES-256 encryption key securely in an offline
  password manager; have a recovery copy separately from the archive.
  Losing the key loses the archive. **Do not commit, screenshot, send or print
  the key in GitHub logs/ChatGPT.**
- Your own machine must have Python 3.11+ installed. Install dependencies
  locally: `python -m pip install -r requirements.txt`.
- On your own private PowerShell session, set `DATABASE_URL` to your existing
  Neon read-only connection (use an actual read-only role if available), and
  `STOCK_ARCHIVE_KEY_HEX` to your *own* key. Never place either in a script,
  code commit or CI workflow.
- Export period limited to **35 calendar days per archive** to minimize load
  and preserve a consistent immutable source transaction per file. If a period
  has no eligible official rows, export fails closed. The source must have an
  up-to-date official listed-issuer snapshot (within 14 days); delisted or
  excluded `1589` are excluded. This is not a survivorship-free historical
  universe.

## Example on a private Windows machine

Use a real owner-controlled directory, here shown as `D:\PrivateStocks`.
Keep it outside the clone of `tw-stock-ai`.

```powershell
New-Item -ItemType Directory -Force "D:\PrivateStocks"
# Set these in your private shell using your credential manager;
# do not paste credentials or keys into the public GitHub repository.
# $env:DATABASE_URL = <your read-only Neon URL>
# $env:STOCK_ARCHIVE_KEY_HEX = <your locally secured 64-hex-character key>

python scripts/twse_local_encrypted_archive.py export `
  --start 2026-11-01 --end 2026-11-20 `
  --archive "D:\PrivateStocks\TWSE-2026-11.twseenc"

python scripts/twse_local_encrypted_archive.py verify `
  --archive "D:\PrivateStocks\TWSE-2026-11.twseenc"

Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:STOCK_ARCHIVE_KEY_HEX -ErrorAction SilentlyContinue
```

Run `verify` on **every archived period**. Make an independently retained,
private copy on a separate physical device, and successfully run `verify`
against that separate copy using the securely recovered key. Keep custody
and restore evidence. If an archive is corrupted, incomplete, truncated,
tampered with, duplicated or unlocked with the wrong key, validation fails.

The encrypted archive includes exact PostgreSQL DECIMAL representations,
nullable OHLCV fields, original timestamps with timezones and source tags.
Streaming chunks are authenticated and the final encrypted footer includes a
whole-export row count and SHA-256. No decrypted rows are written to disk
during verification. The verifier **does not import any data to Neon**.

## Limitations and hard stop

This is a validated *local file-format and read-only export tool*, not a
complete, independently restorable five-year backup system. It does not
provide collection-level archive coverage, enforce an independent copy, audit
private disk retention, or provide a production database restoration path.
No price, index, factor, score or LINE row may be dropped or changed on the
strength of this utility; actual freed Neon storage remains **zero**.

The ongoing official backfill still stops under the same 800MB/50MB free-tier
guard. Moving to a different storage tier requires separately reviewed
backup/restore testing, space accounting, recovery guarantees, and explicit
owner approval for any irreversible production change.
