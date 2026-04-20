ICU_VERSION=66.1
curl -LO https://github.com/unicode-org/icu/releases/download/release-${ICU_VERSION//./-}/icu4c-${ICU_VERSION//./_}-Linux_x64.tgz
tar -xzf icu4c-${ICU_VERSION//./_}-Linux_x64.tgz
cd icu/source
sudo cp -avx lib/* /usr/lib64/
sudo ldconfig
