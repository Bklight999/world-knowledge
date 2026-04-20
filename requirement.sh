conda create -n web-agent python=3.12.7
conda activate web-agent
pip install matplotlib

pip install boto3 botocore openai duckduckgo_search rich numpy openpyxl biopython mammoth markdownify pandas pdfminer-six python-pptx pdf2image puremagic pydub SpeechRecognition bs4 youtube-transcript-api requests transformers protobuf langchain langchain-openai -i http://mirrors.tencent.com/pypi/simple --trusted-host mirrors.tencent.com
# for ck_web2
pip install selenium helium smolagents -i http://mirrors.tencent.com/pypi/simple --trusted-host mirrors.tencent.com

dnf install -y epel-release
dnf install -y \
  poppler-utils \
  java-11-openjdk \
  libreoffice \
  libreoffice-java-common \
  ffmpeg

pip install vllm==0.8.4 -i http://mirrors.tencent.com/pypi/simple --trusted-host mirrors.tencent.com
pip install vertexai -i http://mirrors.tencent.com/pypi/simple --trusted-host mirrors.tencent.com
pip install nvitop -i http://mirrors.tencent.com/pypi/simple --trusted-host mirrors.tencent.com
pip install jsonlines -i http://mirrors.tencent.com/pypi/simple --trusted-host mirrors.tencent.com
pip install vertexai -i http://mirrors.tencent.com/pypi/simple

curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc

nvm install 22.11.0
nvm use 22.11.0
npm install -g npm@10.9.0

sudo yum install -y \
    alsa-lib \
    at-spi2-atk \
    at-spi2-core \
    atk \
    cups-libs \
    dbus-libs \
    expat \
    fontconfig \
    freetype \
    libX11 \
    libXcomposite \
    libXdamage \
    libXext \
    libXfixes \
    libXrandr \
    libXrender \
    libXScrnSaver \
    libXtst \
    libdrm \
    libgbm \
    libxcb \
    libxshmfence \
    mesa-libgbm \
    pango \
    vulkan-loader
