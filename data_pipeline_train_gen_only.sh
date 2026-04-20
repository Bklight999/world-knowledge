#!/usr/bin/env bash
#
# data_pipeline_train_gen_only.sh — keep only Notebook generation
# (Phase 0 + Phase 1); drop Test and Judge stages.
#
# Web-server port pool: 32 servers (3001-3032), each holding up to
# MAX_PER_SERVER concurrent tasks. Tasks fetch a port from a FIFO (blocking)
# and return it when done (first-in / first-out scheduling).
#
# Usage:
#   bash data_pipeline_train_gen_only.sh [batch_size]
#
#   Edit the "urls" array or the "domain" variable below to choose what to run.
#
# Environment variables:
#   MAX_PER_SERVER - max concurrent tasks per web server (default: 1)
#   TOKEN_LIMIT    - guidebook token limit (default: 32000)
#   MODE           - pipeline mode (default: urls)
#                      urls   : use the "urls" array defined below
#                      domain : auto-scan data/${domain}/*_clusters.txt and
#                               extract URLs from every cluster file
#
# Positional arguments:
#   batch_size     - number of URLs processed in parallel per batch (default: 20)
#
# Examples:
#   bash data_pipeline_train_gen_only.sh
#   bash data_pipeline_train_gen_only.sh 3
#   MAX_PER_SERVER=2 bash data_pipeline_train_gen_only.sh 5
#

###############################################
# Pipeline-mode configuration
#   1) urls   : use the explicit URL list in the "urls" array below
#   2) domain : ignore "urls", auto-scan data/${domain}/*_clusters.txt and
#               pick up every URL under that domain
###############################################
MODE="${MODE:-urls}"

# Mode 1 - explicit URL list (edit here)
urls=(
"https://2023.aclweb.org/"
"https://2024.aclweb.org/"  
"https://www2024.thewebconf.org/"
)

# Mode 2 - pick a domain, the script will read every cluster file in data/${domain}/
domain="conference"


BATCH_SIZE="${1:-20}"
MAX_PER_SERVER="${MAX_PER_SERVER:-1}"   # max concurrent tasks per web server
TOKEN_LIMIT="${TOKEN_LIMIT:-32000}"     # guidebook token limit
TOKEN_STR="$(( TOKEN_LIMIT / 1000 ))k"  # e.g. 12000 -> 12k, 16000 -> 16k

LOG_FILE="./pipeline_log/run_train_gen_only.log"

# Global signal dir (shared across batches); cleaned up on exit.
SIGNAL_BASE=$(mktemp -d /tmp/pipeline_train_gen_signals.XXXXXX)
trap 'echo "Stopping all tasks..."; kill $(jobs -p) 2>/dev/null; exec 4>&- 2>/dev/null; rm -rf "$SIGNAL_BASE"; exit' SIGINT SIGTERM EXIT

# Make sure the log directory exists
mkdir -p "$(dirname "$LOG_FILE")"
: > "$LOG_FILE"

echo "===== Start run [train mode - GEN ONLY, MODE=${MODE}] at $(date) =====" | tee -a "$LOG_FILE"

# --- Web-server port pool (FIFO scheduling) ---
# 32 servers x MAX_PER_SERVER slots = total concurrency cap.
# Each task reads one port from the FIFO (blocking), writes it back when done.
WEB_FIFO=$(mktemp -u /tmp/web_fifo_XXXXXX)
mkfifo "$WEB_FIFO"
exec 4<>"$WEB_FIFO"    # open fd 4 for read/write
rm -f "$WEB_FIFO"       # unlink the name; the fd is still valid

ALIVE_PORTS=()
DEAD_PORTS=()
for (( _p=3001; _p<=3032; _p++ )); do
    # Liveness probe (2s timeout)
    if curl -sf --max-time 2 "http://localhost:${_p}/getBrowser" -X POST -H 'Content-Type: application/json' -d '{}' >/dev/null 2>&1 || \
       curl -sf --max-time 2 "http://localhost:${_p}/" >/dev/null 2>&1; then
        ALIVE_PORTS+=("$_p")
        for (( _s=0; _s<MAX_PER_SERVER; _s++ )); do
            echo "$_p" >&4
        done
        echo "  [OK]   Port $_p is alive" | tee -a "$LOG_FILE"
    else
        DEAD_PORTS+=("$_p")
        echo "  [SKIP] Port $_p is NOT responding, excluded from pool" | tee -a "$LOG_FILE"
    fi
done

if [[ ${#ALIVE_PORTS[@]} -eq 0 ]]; then
    echo "[FATAL] No alive web servers found in range 3001-3032! Exiting." | tee -a "$LOG_FILE"
    exit 1
fi

echo "[Port Pool] Initialized: ${#ALIVE_PORTS[@]} alive servers (${ALIVE_PORTS[*]}), ${MAX_PER_SERVER} slots each, $(( ${#ALIVE_PORTS[@]} * MAX_PER_SERVER )) total" | tee -a "$LOG_FILE"

# --- Environment variables ---
export PYTHONPATH=/path/to/cognitive_kernel_GAIA/
export PLAYWRIGHT_BACKEND=browserless
export BROWSERLESS_TARGET_HOST="production-sfo.browserless.io"
export BROWSERLESS_TOKEN="your_browserless_token"
export PHOENIX_ENABLE=true
export HF_TOKEN="your_hf_token"
huggingface-cli login --token "$HF_TOKEN"
export TERM=dumb
export NO_COLOR=1
export PYTHONUNBUFFERED=1

# Project root (resolved from the script's own location)
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

# Helper: convert URL netloc to a safe filename (matches Python url_to_filename)
url_to_safe_name() {
    local raw="${1#*://}"
    raw="${raw%%/*}"
    echo "$raw" | sed 's/[^a-zA-Z0-9]/_/g; s/^_*//; s/_*$//'
}

###############################################
# 0. Collect the URL list according to MODE
#   - urls   : use the user-provided "urls" array directly
#   - domain : scan data/${domain}/*_clusters.txt and extract the base URL
#              from each cluster file's [Prefix] line
###############################################
echo "[Mode] MODE=${MODE}, domain=${domain}" | tee -a "$LOG_FILE"

raw_urls=()
case "$MODE" in
    urls)
        raw_urls=("${urls[@]}")
        echo "[URL List] ${#raw_urls[@]} URLs provided by user" | tee -a "$LOG_FILE"
        ;;
    domain)
        CLUSTER_DIR="${BASE_DIR}/data/${domain}"
        if [[ ! -d "$CLUSTER_DIR" ]]; then
            echo "[FATAL] Domain dir not found: $CLUSTER_DIR" | tee -a "$LOG_FILE"
            exit 1
        fi
        # Walk every cluster file and pull the base URL from its [Prefix] line,
        # e.g. "[Prefix] https://2023.aclweb.org  (34/34 URLs)"
        mapfile -t _cluster_files < <(find "$CLUSTER_DIR" -maxdepth 2 -type f -name '*_clusters.txt' | sort)
        echo "[URL List] Scanning ${#_cluster_files[@]} cluster files in ${CLUSTER_DIR}" | tee -a "$LOG_FILE"
        declare -A _seen=()
        for _cf in "${_cluster_files[@]}"; do
            _base=$(grep -m1 -E '^\[Prefix\][[:space:]]+https?://' "$_cf" | awk '{print $2}')
            if [[ -z "$_base" ]]; then
                # Fallback: first line starting with http(s)://
                _base=$(grep -m1 -E '^https?://' "$_cf" | awk '{print $1}')
            fi
            if [[ -z "$_base" ]]; then
                echo "  [WARN] No URL found in: $_cf" | tee -a "$LOG_FILE"
                continue
            fi
            [[ "$_base" != */ ]] && _base="${_base}/"
            if [[ -n "${_seen[$_base]:-}" ]]; then
                continue
            fi
            _seen[$_base]=1
            raw_urls+=("$_base")
        done
        echo "[URL List] ${#raw_urls[@]} URLs discovered from domain '${domain}'" | tee -a "$LOG_FILE"
        ;;
    *)
        echo "[FATAL] Unknown MODE='${MODE}' (expected: urls | domain)" | tee -a "$LOG_FILE"
        exit 1
        ;;
esac

if [[ ${#raw_urls[@]} -eq 0 ]]; then
    echo "[FATAL] No URLs to process (MODE=${MODE})" | tee -a "$LOG_FILE"
    exit 1
fi

for u in "${raw_urls[@]}"; do
    echo "  - $u" | tee -a "$LOG_FILE"
done

###############################################
# 0-a. Pre-copy cluster files to queue_file/ (9 copies per URL, id 1-9)
###############################################
CLUSTER_DIR="${BASE_DIR}/data/${domain}"
QUEUE_DIR="${BASE_DIR}/queue_file"
mkdir -p "$QUEUE_DIR"

echo "[Pre-copy] Copying cluster files to queue_file/ (9 copies each)..." | tee -a "$LOG_FILE"
for url in "${raw_urls[@]}"; do
    _name_test=$(url_to_safe_name "$url")
    # Look for the cluster file directly under data/, or in any sub-directory
    _src=""
    if [[ -f "${CLUSTER_DIR}/${_name_test}_clusters.txt" ]]; then
        _src="${CLUSTER_DIR}/${_name_test}_clusters.txt"
    else
        # Search sub-directories
        _found=$(find "${CLUSTER_DIR}" -name "${_name_test}_clusters.txt" -type f 2>/dev/null | head -1)
        [[ -n "$_found" ]] && _src="$_found"
    fi

    if [[ -n "$_src" && -f "$_src" ]]; then
        for _id in $(seq 1 9); do
            cp "$_src" "${QUEUE_DIR}/${_name_test}_${_id}_cluster.txt"
        done
        echo "  [COPY] ${_name_test}_clusters.txt -> ${_name_test}_{1..9}_cluster.txt" | tee -a "$LOG_FILE"
    else
        echo "  [WARN] No cluster file found for: ${_name_test}" | tee -a "$LOG_FILE"
    fi
done

###############################################
# 0-b. Filter: skip URLs without cluster file or < 10 URLs (check from queue_file/)
###############################################
all_urls=()

for url in "${raw_urls[@]}"; do
    _name_test=$(url_to_safe_name "$url")
    _cluster="${QUEUE_DIR}/${_name_test}_1_cluster.txt"

    if [[ ! -f "$_cluster" ]]; then
        echo "  [SKIP] No cluster file in queue_file/: ${_name_test}_1_cluster.txt" | tee -a "$LOG_FILE"
        continue
    fi

    _url_count=$(grep -c '^http' "$_cluster" 2>/dev/null || echo 0)
    if [[ "$_url_count" -lt 10 ]]; then
        echo "  [SKIP] Too few URLs ($_url_count < 10): ${_name_test}_1_cluster.txt" | tee -a "$LOG_FILE"
        continue
    fi

    all_urls+=("$url")
    echo "  [OK]   $url  (${_url_count} URLs in cluster)" | tee -a "$LOG_FILE"
done

TOTAL_URLS=${#all_urls[@]}
echo "[URL Filtering] ${TOTAL_URLS} URLs passed (out of ${#raw_urls[@]} raw) at $(date)" | tee -a "$LOG_FILE"

if [[ ${TOTAL_URLS} -eq 0 ]]; then
    echo "[ERROR] No valid URLs. Exiting." | tee -a "$LOG_FILE"
    exit 1
fi

# --- Global config ---
NOTE_IDS=(1 2 3)

# --- vLLM ports --- use 8080-8083 and round-robin across gen tasks
VLLM_PORTS=(8080 8081 8082 8083)
VLLM_PORT_COUNT=${#VLLM_PORTS[@]}
VLLM_TASK_COUNTER=0   # global counter

# --- Stage A: Notebook-generation config ---
GEN_KWARGS='{"temperature": 0.3, "top_p": 0.95, "max_tokens": 8192}'

# Build MAIN_ARGS for the given dynamically-assigned ports.
# Args: $1=web_port, $2=vllm_port
build_main_args_gen() {
    local web_ip="localhost:$1"
    local llm_url="http://localhost:$2/v1/chat/completions"
    echo "{'exec_timeout_with_call': 7200, 'max_steps': 20000, 'web_agent': {'max_steps': 100, 'model': {'call_target': '${llm_url}', 'call_kwargs': ${GEN_KWARGS}}, 'model_multimodal': {'call_target': '${llm_url}', 'call_kwargs': ${GEN_KWARGS}}, 'web_env_kwargs': {'web_ip': '${web_ip}'}}, 'file_agent': {'model': {'call_target': '${llm_url}', 'call_kwargs': ${GEN_KWARGS}}, 'model_multimodal': {'call_target': '${llm_url}', 'call_kwargs': ${GEN_KWARGS}}}, 'model': {'call_target': '${llm_url}', 'call_kwargs': ${GEN_KWARGS}}}"
}

###############################################
# Batch processing: BATCH_SIZE URLs per batch
###############################################
TOTAL_BATCHES=$(( (TOTAL_URLS + BATCH_SIZE - 1) / BATCH_SIZE ))

echo "[Pipeline] Total URLs: ${TOTAL_URLS}, Batch size: ${BATCH_SIZE}, Total batches: ${TOTAL_BATCHES}, Web pool: ${#ALIVE_PORTS[@]}×${MAX_PER_SERVER}=$(( ${#ALIVE_PORTS[@]} * MAX_PER_SERVER )) slots" | tee -a "$LOG_FILE"

for (( batch=0; batch<TOTAL_BATCHES; batch++ )); do
    START_IDX=$(( batch * BATCH_SIZE ))
    END_IDX=$(( START_IDX + BATCH_SIZE ))
    [[ ${END_IDX} -gt ${TOTAL_URLS} ]] && END_IDX=${TOTAL_URLS}

    batch_urls=("${all_urls[@]:${START_IDX}:${BATCH_SIZE}}")
    BATCH_NUM=$(( batch + 1 ))

    echo "" | tee -a "$LOG_FILE"
    echo "##############################################" | tee -a "$LOG_FILE"
    echo "# Batch ${BATCH_NUM}/${TOTAL_BATCHES}: URLs[${START_IDX}..$(( END_IDX - 1 ))]" | tee -a "$LOG_FILE"
    echo "##############################################" | tee -a "$LOG_FILE"
    for u in "${batch_urls[@]}"; do
        echo "  - $u" | tee -a "$LOG_FILE"
    done

    ###############################################
    # Phase 0: Notebook Prompt generation (from cluster files)
    ###############################################
    echo "[Batch ${BATCH_NUM}] [Notebook Prompt] Start at $(date)" | tee -a "$LOG_FILE"
    PROMPT_PIDS=()
    for url in "${batch_urls[@]}"; do
    (
        _nt=$(url_to_safe_name "$url")
        _cf="${QUEUE_DIR}/${_nt}_1_cluster.txt"
        python3 ./notebook_prompt.py --cluster_files "$_cf" --token_limit ${TOKEN_LIMIT} >> "$LOG_FILE" 2>&1
    )&
    PROMPT_PIDS+=($!)
    done
    wait "${PROMPT_PIDS[@]}"
    echo "[Batch ${BATCH_NUM}] [Notebook Prompt] Finished at $(date)" | tee -a "$LOG_FILE"

    ###############################################
    # Phase 1: Notebook Generation + Test Data Prep
    #   Every (URL, ID) pair in the current batch runs in parallel.
    #   Notebook generation needs a web server; pull one from the pool and
    #   return it once the task is done.
    ###############################################
    echo "[Batch ${BATCH_NUM}] [Phase 1] Notebook Generation + Test Data Prep at $(date)" | tee -a "$LOG_FILE"

    TASK_IDX=0
    PHASE1_PIDS=()
    for url in "${batch_urls[@]}"; do
        url_name_raw="${url#*://}"
        url_name_raw="${url_name_raw%%/*}"
        url_name_test=$(url_to_safe_name "$url")

        for id in "${NOTE_IDS[@]}"; do
            local_delay=$((TASK_IDX * 1))
            MY_VLLM_PORT=${VLLM_PORTS[$((VLLM_TASK_COUNTER % VLLM_PORT_COUNT))]}
            VLLM_TASK_COUNTER=$((VLLM_TASK_COUNTER + 1))
            TASK_IDX=$((TASK_IDX + 1))

            (
                note_dir="${BASE_DIR}/output_note/${url_name_raw}"
                task_log="${note_dir}/run_${id}.log"
                mkdir -p "${note_dir}"

                echo "===== Phase 1 for ${url_name_raw} (ID: ${id}) start at $(date) =====" > "$task_log"

                # Step 1: Notebook Generation. id==6 uses a manually-provided notebook and skips this step.
                if [[ "$id" != "6" ]]; then
                    # Pull one available web-server port from the FIFO (blocks until free).
                    read -u 4 MY_WEB_PORT
                    MY_WEB_PORT=$(( 10#$MY_WEB_PORT ))  # strip leading zeros, force base 10

                    echo "[ID $id] Step 1: Generating Notebook (web_port=${MY_WEB_PORT}, vllm_port=${MY_VLLM_PORT})..." | tee -a "$task_log"
                    sleep ${local_delay}
                    MY_MAIN_ARGS_GEN=$(build_main_args_gen "$MY_WEB_PORT" "$MY_VLLM_PORT")
                    NO_NULL_STDIN=1 python3 -u -m System.ckv3.ck_main.main \
                        --updates "${MY_MAIN_ARGS_GEN}" \
                        --input "${BASE_DIR}/questions/notebook_prompt/${url_name_test}_${TOKEN_STR}_${id}.jsonl" \
                        --output "${note_dir}/notebook_${id}.jsonl" \
                        >> "$task_log" 2>&1

                    echo "$MY_WEB_PORT" >&4
                    echo "[ID $id] Step 1: Notebook done, port ${MY_WEB_PORT} released." >> "$task_log"
                else
                    echo "[ID $id] Step 1: SKIPPED (notebook provided manually)" | tee -a "$task_log"
                fi

                # Step 2: Test Data Preparation (CPU only, no web server needed)
                echo "[ID $id] Step 2: Preparing Test Data..." | tee -a "$task_log"
                python3 problem_generation_with_notebook.py \
                    --notebook_id "${id}" \
                    --url "${url}" \
                    --token_limit "${TOKEN_LIMIT}" >> "$task_log" 2>&1

                echo "[ID $id] Phase 1 finished at $(date)" >> "$task_log"
            ) &
            PHASE1_PIDS+=($!)
        done
    done

    echo "[Batch ${BATCH_NUM}] [Phase 1] All ${TASK_IDX} tasks launched at $(date)" | tee -a "$LOG_FILE"

    # Wait for every Phase 1 task in the current batch to finish
    wait "${PHASE1_PIDS[@]}"
    echo "[Batch ${BATCH_NUM}] All Notebook Generation tasks finished at $(date)" | tee -a "$LOG_FILE"

done  # end of per-batch loop

# Clean up the signal root directory
rm -rf "$SIGNAL_BASE"

echo "===== All ${TOTAL_BATCHES} Batches Finished [train mode - GEN ONLY, ${TOTAL_URLS} URLs] at $(date) =====" | tee -a "$LOG_FILE"
