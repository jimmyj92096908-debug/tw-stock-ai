# TWSE 2021 five-year archive: one owner-local command

This is **not** a GitHub Actions data exporter. The owner runs it on the
Windows PC that has the privately retained `DATABASE_URL` and encrypted
`.twsekey` vault. Private source prices, archive keys and passphrases must
never be pasted into a chat, committed to GitHub, printed in CI or uploaded
to an unapproved remote service.

## Prerequisites

- Check out the tested main branch after PR merge and install the existing
  project Python dependencies. The supported CLI is Python (no npm needed).
- Use an **existing private directory outside the public Git repository**
  for `.twseenc` archives. It must not contain symbolic links or untrusted
  archive files.
- Have the existing private AES key vault and independently retained recovery
  copy ready. Keep the vault passphrase private.
- Supply the existing protected `DATABASE_URL` using a secure local method.
  The program uses **READ ONLY** PostgreSQL transactions and never writes rows.
- Check that the 2021 dates remain inside the rolling last-five-year window.
  Expired dates are deliberately not fetched.

## Run (Windows PowerShell)

From the repository root, with the local database environment already
configured and the vault file already created:

```powershell
python -m scripts.twse_2021_owner_local_fast_archive --archive-dir "D:\\private-market-archives" --key-vault "D:\\private-keys\\twse-owner.twsekey"
```

This authenticates all existing local `.twseenc` archives in the given
directory **before** downloading any new public exchange sources. Already
verified source trading days are removed from the candidate list. Remaining
days are sorted into at most eight sessions per batch and separated by month.
Each batch is independently screened against the current official issuer
list, user exclusions (including **1589**), and Neon 2330 date anchors.

The program waits four seconds between official market HTTP GETs, encrypts
source rows directly to private AES-GCM files, verifies each complete archive,
and creates one private `.manifest.json` alongside each file. Existing
files are never overwritten. Rerun the same command after a recoverable
failure: previously completed authenticated source days are skipped.

The console report includes **only aggregate date/file/row counts**.
It never prints source OHLCV, the key, archive paths or connection strings.

## What this does not do

- Does **not** increase Neon stored rows or reduce the current database size
- Does **not** modify LINE or emit trade signals
- Does **not** create or certify an independent offline backup copy or restore
  test; owner must separately preserve both archive and key vault
- Does **not** include currently delisted issuers or prove survivorship-free
  historical analysis
- Does **not** prove dividend-adjusted total returns, five-year completion,
  profitable model performance or release readiness

Do not delete any original Neon/source data. Live model release remains blocked.
