#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    echo "The BCML runtime setup requires an Apple silicon Mac." >&2
    exit 1
fi
for tool in uv cmake; do
    command -v "$tool" >/dev/null || { echo "Install $tool before running BCML setup." >&2; exit 1; }
done

data="$HOME/Library/Application Support/MacNativeMods"
runtime="$data/bcml-runtime"
if [[ -e "$runtime" || -L "$runtime" ]]; then
    "$runtime/bin/python" -B -s -c 'import oead; from bcml import bcml'
    echo "BCML runtime is already installed."
    exit 0
fi
mkdir -p "$data"
scratch=$(mktemp -d "$data/.bcml-setup.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
cd "$scratch"

wheel=bcml-3.10.8-cp39-cp39-macosx_11_0_arm64.whl
curl -fsSL "https://raw.githubusercontent.com/generalOtto/BCML-macOS-App/98117ba8525fef0bbb47e623a3c7c72a873a4c8d/$wheel" -o "$wheel"
curl -fsSL 'https://files.pythonhosted.org/packages/fe/21/e36cd33277bd4e3da223ec1e1cf3c3b9bc599dbe321ea26a37866193ad67/oead-1.2.9.post4.tar.gz' -o oead.tar.gz
printf '%s  %s\n' \
    4bc051c3259173be1fb431484447b096c86163e3f7793f504e786a3c7c7d537b "$wheel" \
    5df951989325d1efef5e154cfb9f8986f8458618b1ba1f538eb7bd46c3a7591a oead.tar.gz \
    | shasum -a 256 -c -
tar -xf oead.tar.gz

# The bundled Abseil and zlib-ng predate Apple silicon.
sed -i '' 's/foreach(_arch IN ITEMS "x86_64" "arm64")/foreach(_arch IN ITEMS "arm64")/' \
    oead-1.2.9.post4/lib/abseil/absl/copts/AbseilConfigureCopts.cmake
sed -i '' "s/cmake_args += \['-DCMAKE_BUILD_TYPE=' + cfg\]/cmake_args += ['-DCMAKE_BUILD_TYPE=' + cfg, '-DWITH_OPTIM=OFF', '-DCMAKE_OSX_ARCHITECTURES=arm64']/" \
    oead-1.2.9.post4/setup.py

uv venv --python 3.9 --seed runtime
uv pip install --python runtime/bin/python --no-deps "./$wheel"
CMAKE_POLICY_VERSION_MINIMUM=3.5 uv pip install --python runtime/bin/python \
    ./oead-1.2.9.post4 'aamp==1.4.1.post1' 'byml==2.4.5.post1' 'botw-utils==0.2.3' \
    packaging 'requests==2.32.5' 'urllib3<2' 'rstb==1.2.2' 'xxhash==3.2.0' 'pywebview==6.2.1' psutil
chmod u+x runtime/lib/python3.9/site-packages/bcml/helpers/7zz
runtime/bin/python -B -s -c 'import oead; from bcml import bcml'
if [[ -e "$runtime" || -L "$runtime" ]]; then
    echo "The BCML runtime was installed by another process." >&2
    exit 1
fi
mv runtime "$runtime"
echo "Installed the local BCML merge runtime."
