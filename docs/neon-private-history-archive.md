# Private Neon historical-source archive (no production deletion)

## Confirmed configuration

- Neon project: `royal-scene-68859981` (Free plan).
- Main branch: `br-purple-smoke-a1t9dmzz`.
- Private Object Storage bucket: `tw-stock-ai-private-history`.
- Public GitHub repository: **never store price archives, private archive keys, presigned URLs or database credentials in the repository or in GitHub artifacts**.
- The existing encrypted archive format is bounded to at most 35 calendar days per source file; one file does **not** represent five years. Export one non-overlapping window at a time and maintain an audited index externally. Historical rows not yet in the database cannot be recovered by exporting the database.

## Operator-only production procedure

Prerequisites: Python requirements installed in a trusted local runtime, a safe folder outside any Git checkout, and a separately secured persistent 32-byte AES key. **Never use a temporary key that may be lost after an automated job**. Store the key independently from the encrypted archive. Set `DATABASE_URL` and `STOCK_ARCHIVE_KEY_HEX` in the environment without printing their values.

1. Export a short, verified official TWSE source interval **read-only**:

   `python -m scripts.twse_local_encrypted_archive export --start 2026-11-02 --end 2026-11-20 --archive /private/archive/twse-202611.twseenc`

2. Run local authentication and full-precision restoration validation:

   `python -m scripts.twse_local_encrypted_archive verify --archive /private/archive/twse-202611.twseenc`

3. Request two **short-lived** Neon Object Storage signed URLs for the exact same object key, e.g. `market=twse/year=2026/twse-202611.twseenc`, one PUT and one GET. Both URLs must refer to the existing private bucket; URLs are bearer credentials. Export them only to the trusted runner's `NEON_PRIVATE_HISTORY_UPLOAD_URL` and `NEON_PRIVATE_HISTORY_DOWNLOAD_URL` variables, not a workflow file or terminal history.

4. Transfer encrypted bytes and verify the separately downloaded copy:

   `python -m scripts.twse_neon_private_object_archive upload-verify --archive /private/archive/twse-202611.twseenc`

   The tool validates both signed destinations, refuses redirects, authenticates the local AES archive, uploads only ciphertext, downloads again to a disposable private path, verifies the complete encrypted SHA-256, and checks the exact original numeric values, source date, and source-vintage fields.

5. Keep a private, external archive inventory containing a nonsecret object key, period, record count, and encrypted SHA-256. Preserve the decryption key securely for future restores; test an independent restore regularly.

**Strict boundaries:** This workflow does not modify Neon PostgreSQL, LINE, model signals, exclusions, or historical price records. A matching remote SHA-256 proves byte-level delivery and successful archive decoding, **not** that five-year coverage is complete or that an unbiased historical stock universe has been reconstructed. Do not delete or migrate source rows until explicit separate authorization and end-to-end model regression checks.

## Read-only historical research loading

After fully authenticated archive verification, a bounded slice can be loaded
into Python for offline model feature computations without a Neon SQL write:

```python
from scripts.twse_neon_private_object_archive import load_verified_research_slice
import os
rows = load_verified_research_slice(
    "/private/archive/twse-202611.twseenc",
    hex_key=os.environ["STOCK_ARCHIVE_KEY_HEX"],
    max_rows=50000,
)
# rows contain exact Decimal OHLCV fields and timezone-aware source timestamps.
# Use only for research; do not publish model outputs or trading signals.
```

The adapter returns nothing unless every encrypted chunk and footer check
passes, and it refuses unbounded memory use. A multi-year production model
still needs a separate, fully validated cross-archive index, correct as-of
feature joins, and full regression validation before any migration.

## Remote-only disaster recovery (no original local archive needed)

The upload/download comparison tool above requires the original local file.
For an independent restore *after losing the local encrypted archive*, use
the remote-recovery tool and an immutable manifest held **outside the bucket**,
plus the long-lived AES-256 key stored separately from both copies.

1. While an authenticated local encrypted archive still exists, create an
   independent nonsecret manifest matching the private object key:

   ```sh
   python -m scripts.twse_neon_remote_restore manifest \
     --archive /private/archive/twse-202611.twseenc \
     --object-key market=twse/year=2026/twse-202611.twseenc \
     > /private/archive/twse-202611.manifest.json
   ```

   Copy the manifest and the decryption key to **two separately controlled,
   durable locations**. Never commit the key, the signed URL, or raw source
   prices into the public GitHub repository.

2. When needed, obtain a fresh short-lived Neon private storage GET URL for
   the **exact manifested object key**, and supply it through the
   `NEON_PRIVATE_HISTORY_DOWNLOAD_URL` environment variable.

3. With a trusted Python runtime and `STOCK_ARCHIVE_KEY_HEX` set securely,
   perform a full standalone remote recovery (the original archive file is
   not required):

   ```sh
   python -m scripts.twse_neon_remote_restore recover \
     --manifest /private/archive/twse-202611.manifest.json
   ```

   The tool enforces the specific project's private storage hostname, exact
   object key, maximum ciphertext size, encrypted SHA-256, authenticated
   footer source-row SHA-256, row count, and full precision/metadata checks.
   Nothing is written into production Neon; rows are not returned unless
   the **whole** downloaded archive verifies.

For offline research, Python callers may request a bounded decoded slice:

```python
from scripts.twse_neon_remote_restore import recover_remote_archive
proof, rows = recover_remote_archive(
    manifest,
    hex_key=secured_key,
    url=short_lived_neon_download_url,
    max_rows=50000,
)
# rows are available only if the whole archive was authenticated.
```

A successful remote-only restore proves the downloaded archive matches the
independent manifest, not full five-year completeness. It never authorizes
deleting production data, loosening the 800 MB current storage guard, or
enabling live model releases. A manifest and separately retained key must
actually exist before considering the private bucket a durable backup.

## First real source batch: two-stage safe operator workflow

To avoid having signed S3 URLs expire while streaming Neon rows, this project
has a two-stage command. **Only a trusted owner-run machine with a durable,
separately retained AES-256 key** can start a real archive. No key is generated
by public CI and the first real production upload is not yet completed.

Choose a private directory **outside Git** which exists and will not be
automatically deleted. Set `DATABASE_URL` and `STOCK_ARCHIVE_KEY_HEX` in
that private runtime (never print them or commit them). The key must be
backed up independently in a secured password manager / offline vault
before archiving. Reuse exactly the same key for remote recovery.

**Stage 1: prepare from official Neon source, SELECT only:**

```sh
python -m scripts.twse_private_first_batch prepare \
  --start 2026-11-02 --end 2026-11-20 \
  --archive /private/archive/twse-202611.twseenc \
  --manifest /private/archive/twse-202611.manifest.json \
  --object-key market=twse/year=2026/twse-202611.twseenc
```

The tool validates the exact official current-issuer roster and the owner's
exclusions via the existing exporter; creates only AES-GCM ciphertext
locally; verifies all rows with exact decimals and source timestamps; and
writes a nonsecret, non-overwritable SHA-256 manifest alongside it.
An archive without verified source rows is rejected. The manifest still
**must be copied to a durable independent location** before any archiving
operation can be treated as disaster recoverable.

**Stage 2: request two new short-lived signed URLs from Neon** for the
private bucket `tw-stock-ai-private-history` and exact key
`market=twse/year=2026/twse-202611.twseenc`: one upload/PUT and one
download/GET. Check that object key does **not already exist** to avoid
replacing an earlier archive. Before PUT, the tool uses the signed GET and
requires a definite HTTP 404 (missing key). An existing key, expired URL,
or uncertain access status causes a safe stop instead of an overwrite. Inject both URLs into the trusted runtime's
`NEON_PRIVATE_HISTORY_UPLOAD_URL` and
`NEON_PRIVATE_HISTORY_DOWNLOAD_URL` environment variables. These URLs
are short-lived bearer credentials; do not save them in GitHub files, logs
or chat.

```sh
python -m scripts.twse_private_first_batch upload-check \
  --archive /private/archive/twse-202611.twseenc \
  --manifest /private/archive/twse-202611.manifest.json
```

Before uploading, the tool verifies the local archive still matches the
manifest and that the remote key is demonstrably absent. After uploading only ciphertext, it downloads the same private
object and performs a *remote-only* full AES-authenticated disaster-recovery
check using the independent manifest. It reports success only on exact byte
hash, canonical-source-row hash and source record-count equality.
If upload or download fails, the original local encrypted file and manifest
remain available for a safe retry with newly issued signed URLs.

**Acceptance gate:** Keep the protected 800 MB/50 MB importer thresholds
unchanged until the first owner-keyed real batch, independently retained
manifest and key, remote restore, and model read-path regression checks all
pass. A successful first slice still does not prove five years are backed
up, does not authorize SQL deletion or index drops, and cannot justify
turning on trading or modifying LINE. The project will not incur new fees.

## Direct-to-archive official five-year gap repair (no PostgreSQL growth)

The original backup path exports **only prices already in Neon**. It cannot
solve missing 2021–2022 history while the free PostgreSQL ceiling is tight.
For owner-approved research on verified current-listed stocks, this additional
path obtains missing whole-market TWSE trading sessions directly from the
official dated `MI_INDEX` feed, validates their dates, codes, prices, coverage
and current official survivor/exclusion roster, and produces a local AES-256
source archive **without inserting a single row into PostgreSQL**.

A real read-only Neon candidate query on 2026-11-22 found the first eight
unprocessed 2022 January trading-day candidates, 2022-01-03 through
2022-01-12 (excluding the weekend); each had 20 observed TWSE bars. These
are **source-validation candidates**, not proof of complete market history.

The tool is explicitly bounded to 8 source dates within a 35-calendar-day
window in the rolling five-year horizon. It will refuse previously processed
receipt dates, absent fresh official company-list snapshots, failed source
fetches, and mixed/duplicate dates. It excludes 1589 and other currently
excluded or delisted stocks. No historical point-in-time universe is claimed.

**Preview: no TWSE requests and no Neon writes**

```sh
python -m scripts.twse_official_direct_archive preview \
  --start 2022-01-01 --end 2022-01-31
```

**Owner-only archive: trusted private runtime with durable pre-backed-up
`STOCK_ARCHIVE_KEY_HEX` and read-only `DATABASE_URL`**

```sh
python -m scripts.twse_official_direct_archive archive \
  --start 2022-01-01 --end 2022-01-31 \
  --archive /private/archive/twse-early-202201.twseenc \
  --manifest /private/archive/twse-early-202201.manifest.json \
  --object-key market=twse/year=2022/twse-early-202201.twseenc
```

The official source acquisition timestamp is the **current retrieval time**;
it must not be used as a supposed historical trading-publication timestamp.
The daily records contain exact source Decimal values, but current-survivor
selection can introduce survivorship bias. Thus this archive is for storage
and research, never stand-alone model approval.

After separately securing the independent manifest and encryption key,
upload/recover the private object using the existing two-stage
`twse_private_first_batch upload-check` command with the matching
`--archive` and `--manifest`. The authenticated remote-only restore
must pass before treating any single slice as durably backed up. Never
lower the original 800MB/50MB Neon guard, delete price records or write
research results to LINE solely because this proof succeeds.

This capability does **not** automatically archive in ChatGPT background
or schedule a credential-bearing GitHub job. Local operator execution
is required. All tests are offline and use synthetic bars only.

## Windows/PowerShell: durable owner-owned archive key custody

Previous storage work is deliberately blocked until an AES-256 key can be
restored after disk loss. The encrypted vault helper provides **two matching,
password-protected files**, rather than a short-lived CI-generated secret.
No plaintext archive key, passphrase, database URL or signed object URL goes
into public GitHub or logs.

**Owner-only prerequisites:** Choose a long unique passphrase, preserve it in
a password manager/offline record, and provide a genuinely **independent**
recovery destination (for example a removable offline drive, not merely a
second directory on the same physical disk). Keep both storage paths outside
the public Git checkout. This software can validate byte-level equality and
decryptability, **not** verify different physical media or that the password
has been independently backed up.

Example on the user's trusted Windows PowerShell, from project root
(change the recovery drive letter to a real user-owned external drive):

```powershell
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\tw-stock-private" | Out-Null
New-Item -ItemType Directory -Force "E:\tw-stock-recovery" | Out-Null
python -m scripts.twse_archive_key_vault init `
  --vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
  --recovery "E:\tw-stock-recovery\history.twsekey"
```

The helper prompts privately for the passphrase twice, generates 32 random
key bytes in memory, and stores the SAME encrypted vault in both locations.
It refuses any existing vault and any path inside Git. **Do not repeat init**
after starting to archive: making a different key will make earlier archives
unreadable. Test recovering both copies before using production:

```powershell
python -m scripts.twse_archive_key_vault verify `
  --vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey" `
  --recovery "E:\tw-stock-recovery\history.twsekey"
```

No archive key is printed by either command. If one device is lost, decrypt
using the independently held encrypted key file and preserved passphrase.
If BOTH files and their backups are lost, the archives cannot be recovered.
Keep a separately stored copy of the nonsecret archive manifest too.

A private 2022 source gap archive can then be prepared without exposing
plaintext key material in environment variables or command history:

```powershell
# DATABASE_URL must already be configured privately in this trusted shell.
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\tw-stock-private\prices" | Out-Null
python -m scripts.twse_official_direct_archive archive `
  --start 2022-01-01 --end 2022-01-31 `
  --archive "$env:LOCALAPPDATA\tw-stock-private\prices\twse-early-202201.twseenc" `
  --manifest "$env:LOCALAPPDATA\tw-stock-private\prices\twse-early-202201.manifest.json" `
  --object-key "market=twse/year=2022/twse-early-202201.twseenc" `
  --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey"
```

For the actual private Neon upload, obtain short-lived PUT and GET URLs from
the authorized Neon storage console for exactly this object. **Never paste
these URLs into public code or chats**. In the trusted shell, run:

```powershell
python -m scripts.twse_private_first_batch upload-check `
  --archive "$env:LOCALAPPDATA\tw-stock-private\prices\twse-early-202201.twseenc" `
  --manifest "$env:LOCALAPPDATA\tw-stock-private\prices\twse-early-202201.manifest.json" `
  --key-vault "$env:LOCALAPPDATA\tw-stock-private\history.twsekey"
```

The resulting archive is considered **remote backed up only** after the
manifest-bound private PUT and separately downloaded remote-only AES restore
have actually passed, the manifest is backed up independently, and the
recovery vault/long unique passphrase can be recovered. This must not lead
to deletion of historical PostgreSQL rows, provider payment, or model release.
Do not run owner vault creation in GitHub Actions or an ephemeral runner.

## Storage-ceiling decision

The guarded TWSE importer currently uses an internal physical PostgreSQL ceiling of **800,000,000 bytes**, with a further **50,000,000-byte maintenance reserve** and pessimistic per-date growth allowance. Although the Neon Free project limit is 1 GiB, that provider limit and the physical PostgreSQL size are **not interchangeable**, and the project may contain other branch/storage overhead. Raising the internal ceiling to 900 MB would change automatic scheduled production import behavior. **Do not raise it before a real, durable, independently restored archive and a verified project-level allowance assessment.** Never change plans or incur paid charges to bypass these gates.

## Tests

`python -m unittest tests.test_twse_private_first_batch tests.test_twse_neon_private_object_archive tests.test_twse_neon_remote_restore tests.test_twse_local_encrypted_archive -v`

Offline tests also exercise remote-only recovery after removal of the original local encrypted file. They simulate transport and never upload synthetic rows to the actual bucket. Real upload and download have not passed until the operator runs the complete procedure and validates independent private storage receipts.
