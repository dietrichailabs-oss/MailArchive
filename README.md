# MailArchive

<p align="center">
  <img src="assets/mailarchive.png" width="128" height="128" alt="MailArchive application icon">
</p>

**MailArchive is a local-first Microsoft 365 email archival utility for Windows 11 x64.**

Preserve first. Verify locally. Only then optionally clean up verified originals.

MailArchive helps you select Microsoft 365 mailbox folders and a date range, preview the planned archive, and preserve original `.eml` messages and attachments in a local destination you control. It independently verifies archive integrity before any message can become eligible for optional cleanup.

## Major features

- Sign in to Microsoft 365 using a public desktop-client flow.
- Select one or more mailbox folders and a date range.
- Choose a local archive destination and preview the plan before starting.
- Preserve original `.eml` messages and their attachments.
- Independently verify local archive integrity with SHA-256-based checks.
- Search archived mail locally and open messages offline.
- View archived attachments without reconnecting to the mailbox.
- Move an archive to another folder or drive and reopen it there.
- Cancel safely and resume archive work.
- Optionally move eligible, still-verified online originals to Microsoft 365 Deleted Items.

## Safety design

MailArchive archives and verifies messages locally before they can become eligible for cleanup. Version 1 cleanup moves eligible **VERIFIED** online originals to Microsoft 365 **Deleted Items only**, after explicit user confirmation.

MailArchive Version 1 has no permanent-delete path. Moving messages to Deleted Items does not guarantee mailbox quota recovery and does not override Microsoft 365 retention or organizational policies.

## Requirements

- Windows 11 x64
- A Microsoft 365 account for live mailbox access
- A local folder or drive with sufficient space for the archive

After archival, preserved mail remains locally searchable and readable offline.

## Download

Download the exact approved package from the [MailArchive v1.0.0-rc1 release](https://github.com/dietrichailabs-oss/MailArchive/releases/tag/v1.0.0-rc1) or the [official Dietrich AI Labs download center](https://www.dietrichailabs.com/downloads.html).

Package: `MailArchive_1.0.0-rc1_Windows11_x64_Public.zip`

```text
ZIP SHA-256
D295B64191EEAFD8B01E45B7BE320DF04F4347AEB92E341ED88319DD46E16542

Signed installer SHA-256
E8ED8315C7F07872497AA924F39F979A364600BC2EC62B78DAB9BCBADF80710D
```

## Signing disclosure

The installer is Authenticode signed by `CN=Dietrich AI Labs` using a Dietrich AI Labs self-signed certificate included in the package. This is not a publicly trusted commercial certificate. Other Windows systems may show SmartScreen or Unknown Publisher reputation warnings until the certificate is trusted or reputation develops.

## Source and license

The source published here corresponds to the approved MailArchive 1.0.0-rc1 release snapshot. MailArchive is proprietary freeware, not open-source software.

License: `LicenseRef-Dietrich-AI-Labs-Freeware-1.0`, Dietrich AI Labs MailArchive Freeware License. See [LICENSE.txt](LICENSE.txt).

## Official links and support

- [MailArchive product page](https://www.dietrichailabs.com/mailarchive.html)
- [Dietrich AI Labs downloads](https://www.dietrichailabs.com/downloads.html)
- [Dietrich AI Labs](https://www.dietrichailabs.com/)
- [Support](https://www.dietrichailabs.com/contact.html)

