#!/bin/sh
# Known vulnerabilities in the installed Python dependencies (pip-audit, PyPI
# advisory database). Run by CI's `audit` job and by `just ci` / `just audit`,
# so the two always ignore the same advisories.
#
# --skip-editable: meshbee-core is this repository, not a PyPI package.
#
# Each ignored advisory has no fixed release and does not apply to how Meshbee
# uses the package. Remove its line once a fix ships or the package goes.
#
# PYSEC-2026-4298 (CVE-2026-85394), python-jose 3.5.0: an attacker holding the
#   service's *public* key can forge HS256 tokens when the accepted algorithms
#   are not restricted. Meshbee signs HS256 with a shared secret (no public key)
#   and api/auth.py decodes with algorithms=[JWT_ALGORITHM].
# PYSEC-2026-1325 (CVE-2024-23342), ecdsa 0.19.2, pulled in by python-jose: a
#   timing side channel on ECDSA *signing*. Meshbee never signs with ECDSA, and
#   upstream will not fix it.
set -eu

exec pip-audit --skip-editable \
    --ignore-vuln PYSEC-2026-4298 \
    --ignore-vuln PYSEC-2026-1325
