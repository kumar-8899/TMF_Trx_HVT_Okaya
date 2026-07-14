# ks_release_signer — self-hosted Keystation release signer (for CI)

`canonical.py` is **vendored verbatim** from the Keystation issuer
(`server/app/modules/issuance/canonical.py`) so a CI-signed `.ksupdate` is
byte-identical to what the issuer would produce and the station's Rust core
verifies it. Keep it in sync with Keystation; it is the only drift-sensitive part.

`sign_update.py` builds + signs a framework release manifest from a `RELEASE.json`
using an **intermediate** signing key (Ed25519) + a root-signed intermediate cert,
both supplied via env (GitHub Actions secrets). The **root private key never touches
CI** — the cert is minted once offline during the root ceremony.

Production note: the canonical Keystation flow signs on the issuer (HSM). This
in-CI signer is the self-hosted equivalent for a single-vendor pipeline.
