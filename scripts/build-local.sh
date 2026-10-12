#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
    echo "Usage: build-local.sh REVISION SIGNING_HOME FINGERPRINT [WWWROOT]" >&2
    exit 2
fi
M13_REVISION=$1
M13_SIGNING_HOME=$2
M13_FINGERPRINT=$3
test -d "$M13_SIGNING_HOME" || { echo 'Signing home does not exist' >&2; exit 1; }
gpg --homedir "$M13_SIGNING_HOME" --batch --list-secret-keys "$M13_FINGERPRINT" >/dev/null
M13_REPOSITORY=$(cd "$(dirname "$0")/.." && pwd)
M13_WWWROOT=${4:-$M13_REPOSITORY/wwwroot}
cd "$M13_REPOSITORY"
export PYTHONPATH="$M13_REPOSITORY/src"
if [ ! -f ".cache/packages-$M13_REVISION/build-input.json" ]; then
    /usr/bin/python3 -m ophub_kernel.cli build --output ".cache/packages-$M13_REVISION" --revision "$M13_REVISION"
else
    /usr/bin/python3 -m ophub_kernel.cli check-build --packages ".cache/packages-$M13_REVISION"
fi
/usr/bin/python3 -m ophub_kernel.cli repository --packages ".cache/packages-$M13_REVISION" \
    --output "$M13_WWWROOT" --signing-home "$M13_SIGNING_HOME" --fingerprint "$M13_FINGERPRINT"
