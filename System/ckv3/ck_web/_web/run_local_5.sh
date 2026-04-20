export PLAYWRIGHT_BACKEND=local #browserless # 原来默认是local
export BROWSERLESS_TARGET_HOST="production-sfo.browserless.io"
export BROWSERLESS_TOKEN="2SqSru8CiyLEvMZd30c00706aea0cd8c6d687e0e465a9fa91"

LISTEN_PORT=3005 npm start 2>&1 | tee ./server-log/server-3005-output.txt
