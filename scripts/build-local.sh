#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
    echo "Usage: build-local.sh REVISION SIGNING_HOME FINGERPRINT [WWWROOT]" >&2
    exit 2
fi
OPHUB_REVISION=$1
OPHUB_SIGNING_HOME=$2
OPHUB_FINGERPRINT=$3
test -d "$OPHUB_SIGNING_HOME" || { echo 'Signing home does not exist' >&2; exit 1; }
gpg --homedir "$OPHUB_SIGNING_HOME" --batch --list-secret-keys "$OPHUB_FINGERPRINT" >/dev/null
OPHUB_REPOSITORY=$(cd "$(dirname "$0")/.." && pwd)
OPHUB_WWWROOT=${4:-$OPHUB_REPOSITORY/wwwroot}
OPHUB_PROFILE=generic
OPHUB_ARGS=()
case ${OPHUB_WITH_M13_PROFILE:-0} in
    0) ;;
    1) OPHUB_PROFILE=m13; OPHUB_ARGS+=(--with-m13-profile) ;;
    *) echo 'OPHUB_WITH_M13_PROFILE must be 0 or 1' >&2; exit 2 ;;
esac
cd "$OPHUB_REPOSITORY"
export PYTHONPATH="$OPHUB_REPOSITORY/src"
OPHUB_PACKAGES=".cache/packages-$OPHUB_PROFILE-$OPHUB_REVISION"
if [ ! -f "$OPHUB_PACKAGES/build-input.json" ]; then
    /usr/bin/python3 -m ophub_kernel.cli build --output "$OPHUB_PACKAGES" --revision "$OPHUB_REVISION" "${OPHUB_ARGS[@]}"
else
    /usr/bin/python3 -m ophub_kernel.cli check-build --packages "$OPHUB_PACKAGES" "${OPHUB_ARGS[@]}"
fi
/usr/bin/python3 -m ophub_kernel.cli repository --packages "$OPHUB_PACKAGES" \
    --output "$OPHUB_WWWROOT" --signing-home "$OPHUB_SIGNING_HOME" --fingerprint "$OPHUB_FINGERPRINT"
