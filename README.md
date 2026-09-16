<div align="center">
  <img src="assets/mailarchive.png" alt="Mail Archive 1.0.0 application icon" width="112">

# Mail Archive 1.0.0

**Local-first Microsoft 365 email archiving for Windows.**  
Preserve your original messages. Verify them locally. Read them in a native mail viewer.

<p>
  <a href="https://github.com/dietrichailabs-oss/MailArchive/releases/tag/v1.0.0"><img alt="Release 1.0.0" src="https://img.shields.io/badge/release-1.0.0-0EA5E9?style=for-the-badge"></a>
  <img alt="Windows 11 x64" src="https://img.shields.io/badge/Windows-11%20x64-0078D4?style=for-the-badge&logo=windows11&logoColor=white">
  <img alt="Microsoft 365" src="https://img.shields.io/badge/Microsoft%20365-Mail-5E5E5E?style=for-the-badge&logo=microsoft&logoColor=white">
  <img alt="Local first" src="https://img.shields.io/badge/design-local--first-06B6D4?style=for-the-badge">
  <img alt="Proprietary freeware" src="https://img.shields.io/badge/license-proprietary%20freeware-475569?style=for-the-badge">
</p>

<p>
  <a href="https://github.com/dietrichailabs-oss/MailArchive/releases/download/v1.0.0/Mail_Archive_1.0.0_Clean_Public.zip"><strong>⬇ Download Mail Archive 1.0.0</strong></a>
  &nbsp;&nbsp;•&nbsp;&nbsp;
  <a href="#whats-new-and-fixed"><strong>What's New &amp; Fixed</strong></a>
  &nbsp;&nbsp;•&nbsp;&nbsp;
  <a href="https://github.com/dietrichailabs-oss/MailArchive/releases/tag/v1.0.0"><strong>Release Page</strong></a>
  &nbsp;&nbsp;•&nbsp;&nbsp;
  <a href="https://www.dietrichailabs.com/mailarchive.html"><strong>Product Page</strong></a>
</p>
</div>

---

> [!IMPORTANT]
> **Preserve first. Verify locally. Only then optionally move still-verified originals to Deleted Items.**  
> Mail Archive 1.0.0 has **no permanent-delete operation** and does not automatically empty Microsoft 365 Deleted Items. Keep a separate backup of your archive.

## Download & verify

**Current public version: Mail Archive 1.0.0** · **Publisher: Dietrich AI Labs** · **Target: Windows 11 x64**

### [⬇ Download the current public package](https://github.com/dietrichailabs-oss/MailArchive/releases/download/v1.0.0/Mail_Archive_1.0.0_Clean_Public.zip)

The [published release](https://github.com/dietrichailabs-oss/MailArchive/releases/tag/v1.0.0) provides a **36.8 MB** ZIP containing only:

- `Mail_Archive_1.0.0_Setup.exe`
- `LICENSE.txt`
- `SHA256_CHECKSUMS.txt`

| Artifact | Exact size | SHA-256 |
|---|---:|---|
| `Mail_Archive_1.0.0_Clean_Public.zip` | 36,803,052 bytes | `3A3157B34348F94F32B90B0418556CF44D0FB046EB2411ABB281555A3F2192AB` |
| Signed `Mail_Archive_1.0.0_Setup.exe` | 37,312,464 bytes | `EB91EE487E419EF197EAFB794D32AAE875F51D44A6AEAB14C8A4AC57A6FD8A24` |

The ZIP identity above is the published release-asset identity. The installer identity is the independent-QA-approved signed installer. The public ZIP is a reduced three-file package, distinct from the six-file signing-review package; do not substitute a private QA handoff, signing kit, or source-code download for this installer package.

Check your downloaded ZIP in PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\Mail_Archive_1.0.0_Clean_Public.zip
```

Compare the result with the ZIP checksum above. After extracting, use `SHA256_CHECKSUMS.txt` and the installer checksum to check the contents. Stop if a checksum differs.

## What's new and fixed

### Native, Outlook-style archive reading

Read archived mail **inside the application**, instead of needing to launch a browser for normal use. The native three-pane layout puts the folder tree on the left, the message list in the middle, and the selected message on the right.

Choose an existing archive or browse to its folder on disk, then select a mailbox folder to see its archived messages. The reader includes nested folders and counts, **All Archived Mail**, current-folder or all-archive search, sorting, attachment saving, original `.eml` export, and raw headers. Resizable panes and saved view settings make longer browsing sessions easier. The browser viewer remains available as an explicit alternative.

**Opening a completed local archive does not require Microsoft sign-in, Outlook, or downloading the messages again.**

### Faster cleanup without removing per-message checks

The cleanup path no longer repeatedly loads and parses the entire manifest for every message. It streams the manifest into a protected, disk-backed index once per operation and processes cleanup in **controlled groups of up to four messages**.

Each message still receives current local-integrity and Microsoft identity checks before movement. Outcomes are recorded individually. An uncertain move is held for reconciliation rather than blindly retried, and previously confirmed moves remain preserved across restarts.

### More useful progress, stopping, and continuation

Long operations expose progress, per-run outcome counts, elapsed time, a **confirmed moves-per-minute** reading, and an estimated remaining time. Progress updates are coalesced to avoid building an unnecessary interface backlog.

Resuming an incomplete archive skips messages already verified locally and continues missing or failed work. Stopping cleanup prevents another group from starting while allowing already-submitted requests to finish and have their outcomes recorded. Closing during cleanup follows that safe-stop path.

### Complete access to large message lists

The native reader uses **200-row pages**, not a 200-message archive limit. First, Previous, Next, Last, and Go navigation make the complete matching set reachable without loading every email body into the interface at once. Folder and search totals remain visible.

Manifest indexing and both native/browser result traversal were exercised with **one million synthetic metadata records**. These were metadata-scale tests, not one million live mailbox moves or one million fully preserved email files.

### Reader layout and Windows packaging corrections

Navigation and page controls retain space in smaller windows; counts, folder captions, and notices wrap instead of squeezing out important controls. Attachment and stop controls have dedicated layout space, and message rows account for font metrics.

The Windows build's version-resource path was corrected, cleanup-report and installer build identities were reconciled, and package evidence checks were corrected to use each test report's actual result field and the exact tested source identity.

The signed installer retains the approved application payload and uses the established **Dietrich AI Labs** certificate. See [Signing & Windows trust](#signing--windows-trust) for its limitations.

## Observed field result

One completed field run's application-generated reports recorded **20,075 verified archived messages** and **20,075 successful moves to Deleted Items**, with **zero failed, missing, skipped, uncertain, or remaining cleanup items**. The archive and cleanup message-ID lists matched one-for-one.

Cleanup took approximately **2 hours, 38 minutes, 37 seconds**, averaging **126.6 confirmed moves per minute**—about **2.11 per second**. This is one observed run, not a guaranteed rate or a claim of 122 messages per second. Storage, message size, network conditions, and service responses can affect performance. Report reconciliation is not an independent inspection of the live mailbox or a fresh re-hash of every archived file. Private account and message identifiers are not published here.

## How it works

1. **Archive:** sign in to Microsoft 365, choose folders and a date range, select a destination, and review the preview. Original `.eml` messages and attachments are preserved locally.
2. **Verify:** check the preserved content and archive integrity before considering cleanup.
3. **Read:** use **View Mail** or open an existing archive. Select its folder on disk, choose a mailbox folder, and browse or search locally.
4. **Optionally clean up:** explicitly confirm moving eligible, still-verified originals to Microsoft 365 Deleted Items. Archiving or reading alone does not authorize this step.

Before upgrading, finish or safely stop existing jobs, close the application, and back up the **entire archive folder and its reports**. A completed archive can be reopened after moving it to another suitable folder or drive.

## Safety & privacy

The core safety requirement is that an online message must not be moved unless its local copy has first been preserved and verified. Cleanup is optional, requires explicit consent, and rechecks current local integrity and provider identity before dispatch. Uncertain outcomes are not automatically replayed. The application does not permanently delete messages or empty Deleted Items.

Moving messages to Deleted Items **does not guarantee freed mailbox quota**. Keep archive size, completed-move counts, and mailbox storage usage separate; organization retention policies can also affect storage behavior.

Live archival uses delegated `Mail.Read`; cleanup requests `Mail.ReadWrite` only for the optional write capability. No Send Mail permission is required. Authentication tokens use Windows DPAPI protection rather than a plaintext fallback, and application logging paths redact bearer/access/refresh tokens.

Local reading does not require mailbox access. Native message content is rendered as restricted static content, not an unrestricted web page. The optional browser viewer retains loopback-only access, restrictive Content Security Policy, remote-resource blocking, sanitization, controlled inline resources, and integrity checks before serving content.

Use appropriate storage encryption, access permissions, and a separate backup for sensitive archives. Reports can contain account and message identifiers; do not attach unredacted reports to public issues.

## Reports & known limitations

Archive and cleanup reports are saved in the archive's **`reports`** folder. Relevant files include `archive_report.json`, `cleanup_report.json`, and `cleanup_status.json`. Cleanup reports distinguish requested, processed, moved, skipped, failed, missing, uncertain, and remaining work; the status report also records elapsed time and phase timings. The completion screen does not yet provide a direct **Open Report** shortcut.

**Known non-blocking display issue:** the fast completion/recovery summary can show **“Local structural issues found: 0”** even when that path did not perform a structural scan. Do not interpret that line as a fresh integrity check. Use **Verify Archive** for an explicit verification. This wording issue remains present in the approved version; it is not listed above as a completed fix.

The native reader supports common formatting, simple table rows, plain text, and verified local raster images. It is **not Outlook's full HTML/CSS engine**: complex layouts are simplified, active hyperlinks and interactive content are not rendered, and remote message resources are blocked. Original message exports remain available. No Outlook installation or Microsoft affiliation is implied by the familiar three-pane layout.

## Requirements

| Requirement | Details |
|---|---|
| Release target | Windows 11 x64 |
| Live archival and cleanup | Microsoft 365 account, network access, and the required delegated permissions |
| Existing local archive reading | No Microsoft sign-in or Outlook installation required |
| Storage | A suitable writable archive location with enough capacity, appropriate access controls, and a separate backup |

Windows 10 is not an advertised release target.

## Signing & Windows trust

The installer is Authenticode-signed with the established self-signed **Dietrich AI Labs** code-signing certificate:

```text
Subject / issuer: CN=Dietrich AI Labs
SHA-1 certificate identity thumbprint: C7FB96DDE901E3D57637804A63AC11FDDE0B5D32
Certificate DER SHA-256: B067E75AFCB37F986F461FE2E341DC3F5C1AFC4AF8D16C44E9B0A1FA5B33C81F
Certificate expiry: 2031-07-15 18:56:19 UTC
File-signature digest: SHA-256
Trusted timestamp: None
```

The certificate is embedded in the installer. A separate `.cer` is **not included in the current three-file public ZIP**, and the private signing key is never distributed. The SHA-1 thumbprint above identifies the certificate; it is not the file-signature digest.

> [!NOTE]
> Self-signing does not establish public certificate-authority trust or guarantee that Windows SmartScreen, unknown-publisher, or reputation warnings disappear. Cryptographic signature integrity and Windows trust are different checks. No root certificate is automatically installed. The absent trusted timestamp and certificate expiry limit long-term signature validity under the verifier's policy. This is not a claim of Microsoft Verified Publisher or Entra Publisher Verification.

## Validation scope

The unchanged product and the signed installer completed independent QA. Review covered archive/cleanup safety, uncertain-outcome handling, native and browser readers, metadata-scale traversal, signature and payload binding, package checks, fresh installation, repair, predecessor upgrades, same-version unsigned-to-signed replacement, moved archives, and uninstall/archive survival. The existing LOW structural-summary display issue remained non-blocking.

Automated Windows review ran on **Microsoft Windows Server 2025 Datacenter, build 26100 x64**. The product review recorded an explicit owner-approved platform waiver; those runs are not described as literal Windows 11 tests. Field use, signing-workstation observations, automated tests, and independent QA are separate evidence categories.

Approval binds to exact reviewed bytes. The signed installer checksum above identifies the approved executable; the published three-file ZIP has its own separate checksum. Rebuilding, re-signing, or repackaging creates a new artifact identity and must not silently inherit a different package's approval.

## Source snapshot & license

**The public source snapshot currently predates the Mail Archive 1.0.0 binary release.** [`SOURCE_IDENTITY.json`](SOURCE_IDENTITY.json) describes the source snapshot retained in this repository, not the current downloadable installer. Do not assume GitHub's automatic **Source code** archives reproduce the binary linked above. This README update does not replace the source tree or alter the reviewed installer.

Mail Archive is **proprietary freeware**, not open-source software.

- License: `LicenseRef-Dietrich-AI-Labs-Freeware-1.0`
- Full terms: [`LICENSE.txt`](LICENSE.txt)
- Publisher: **Dietrich AI Labs**

## Official links

[Download Mail Archive 1.0.0](https://github.com/dietrichailabs-oss/MailArchive/releases/download/v1.0.0/Mail_Archive_1.0.0_Clean_Public.zip) · [Release page](https://github.com/dietrichailabs-oss/MailArchive/releases/tag/v1.0.0) · [All releases](https://github.com/dietrichailabs-oss/MailArchive/releases)  
[Product page](https://www.dietrichailabs.com/mailarchive.html) · [Download center](https://www.dietrichailabs.com/downloads.html) · [Support](https://www.dietrichailabs.com/contact.html) · [Report an issue](https://github.com/dietrichailabs-oss/MailArchive/issues)

---

<p align="center">
  <strong>Dietrich AI Labs</strong><br>
  Local-first tools built around user control, verifiable artifacts, and practical Windows workflows.
</p>
