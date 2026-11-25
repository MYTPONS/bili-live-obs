# Security

`bls login` stores account credentials in `~/.config/bls/credentials.json` with mode 0600. Stream keys are also local-only.

Never commit:

- credential or stream-key files
- QR screenshots or account cookies
- OBS configuration or logs
- generated recordings
- personal room IDs when they are not needed for tests

This tool calls non-public Bilibili endpoints and can stop working when the upstream API changes. Review the source before running `bls go`.
