FROM python:3.12.3-slim

RUN apt update && apt install -y git unzip wget && \
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt install ./google-chrome-stable_current_amd64.deb -y && \
    rm -rf /var/lib/apt/lists/* ./google-chrome-stable_current_amd64.deb

RUN version=$(google-chrome -version |awk '{print $3}') && \
    wget https://storage.googleapis.com/chrome-for-testing-public/$version/linux64/chromedriver-linux64.zip && \
    unzip chromedriver-linux64.zip && \
    git clone https://github.com/ZQYKing/Rainyun-qiandao.git

WORKDIR /Rainyun-qiandao
RUN pip3 install -r requirements.txt && \
    cp ../chromedriver-linux64/chromedriver  ./ && \
    rm -rf ../chromedriver-linux64 && \
    rm -rf ../chromedriver-linux64.zip && \
    chmod +x chromedriver

CMD ["python3", "rainyun.py"]
