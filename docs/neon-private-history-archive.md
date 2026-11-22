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

## Storage-ceiling decision

The guarded TWSE importer currently uses an internal physical PostgreSQL ceiling of **800,000,000 bytes**, with a further **50,000,000-byte maintenance reserve** and pessimistic per-date growth allowance. Although the Neon Free project limit is 1 GiB, that provider limit and the physical PostgreSQL size are **not interchangeable**, and the project may contain other branch/storage overhead. Raising the internal ceiling to 900 MB would change automatic scheduled production import behavior. **Do not raise it before a real, durable, independently restored archive and a verified project-level allowance assessment.** Never change plans or incur paid charges to bypass these gates.

## Tests

`python -m unittest tests.test_twse_neon_private_object_archive tests.test_twse_local_encrypted_archive -v`

Offline tests also exercise remote-only recovery after removal of the original local encrypted file. They simulate transport and never upload synthetic rows to the actual bucket. Real upload and download have not passed until the operator runs the complete procedure and validates independent private storage receipts.
