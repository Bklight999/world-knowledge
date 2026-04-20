for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32; do
    port=$((3000 + i))
    tmux new-session -d -s "server${i}"
    tmux send-keys -t "server${i}" "cd /path/to/cognitive_kernel_GAIA/System/ckv3/ck_web/_web && conda activate web-agent && export PLAYWRIGHT_BACKEND=local && export BROWSERLESS_TARGET_HOST='production-sfo.browserless.io' && export BROWSERLESS_TOKEN='your_browserless_token' && LISTEN_PORT=${port} npm start 2>&1 | tee ./server-log/server-${port}-output.txt" Enter
done