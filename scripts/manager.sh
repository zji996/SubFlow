#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs"

# Prefer Astral official uv (avoids snap-uv issues on some systems).
if [[ -f "${HOME}/.local/bin/env" ]]; then
  # shellcheck disable=SC1090
  source "${HOME}/.local/bin/env"
fi

if [[ -t 1 ]]; then
  RED=$'\033[0;31m'
  GREEN=$'\033[0;32m'
  YELLOW=$'\033[0;33m'
  BLUE=$'\033[0;34m'
  NC=$'\033[0m'
else
  RED='' GREEN='' YELLOW='' BLUE='' NC=''
fi

log_info() { printf '%s[INFO]%s %s\n' "${BLUE}" "${NC}" "$*"; }
log_ok() { printf '%s[OK]%s %s\n' "${GREEN}" "${NC}" "$*"; }
log_warn() { printf '%s[WARN]%s %s\n' "${YELLOW}" "${NC}" "$*"; }
log_error() { printf '%s[ERROR]%s %s\n' "${RED}" "${NC}" "$*" >&2; }

API_PID="${LOG_DIR}/api.pid"
WORKER_PID="${LOG_DIR}/worker.pid"
WEB_PID="${LOG_DIR}/web.pid"

API_LOG="${LOG_DIR}/api.log"
WORKER_LOG="${LOG_DIR}/worker.log"
WEB_LOG="${LOG_DIR}/web.log"

API_PORT_DEFAULT="8100"
WEB_PORT_DEFAULT="5173"
LOG_LINES_DEFAULT="50"

usage() {
  cat <<'EOF'
SubFlow Development Manager

Usage:
  bash scripts/manager.sh <command> [services...] [options]

Commands:
  up        Start services (default: api worker web)
  down      Stop services (default: api worker web)
  restart   Restart services
  status    Show service status
  logs      View service logs
  check     Check environment dependencies
  health    Run health checks

Services:
  api       FastAPI backend (default port: 8100)
  worker    Background worker
  web       Vite frontend (default port: 5173)

Options:
  --api-port N    API server port (default: 8100)
  --web-port N    Web server port (default: 5173)
  -f, --follow    Follow log output (logs command)
  -n, --lines N   Tail last N lines (logs command, default: 50)
  -h, --help      Show this help message

Examples:
  bash scripts/manager.sh up
  bash scripts/manager.sh up api worker
  bash scripts/manager.sh down
  bash scripts/manager.sh status
  bash scripts/manager.sh logs api
  bash scripts/manager.sh logs worker -f
  bash scripts/manager.sh check
  bash scripts/manager.sh health
EOF
}

ensure_log_dir() {
  mkdir -p "${LOG_DIR}"
}

read_pid() {
  local pid_file="$1"
  if [[ ! -f "${pid_file}" ]]; then
    return 1
  fi
  local pid
  pid="$(tr -d ' \t\r\n' <"${pid_file}" || true)"
  if [[ -z "${pid}" ]]; then
    return 1
  fi
  echo "${pid}"
}

pid_running() {
  local pid="$1"
  kill -0 "${pid}" >/dev/null 2>&1
}

start_bg() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  shift 3

  ensure_log_dir

  local existing_pid=""
  if existing_pid="$(read_pid "${pid_file}" 2>/dev/null || true)"; then
    if [[ -n "${existing_pid}" ]] && pid_running "${existing_pid}"; then
      log_warn "[${name}] already running (pid/pgid=${existing_pid})"
      return 0
    fi
    rm -f "${pid_file}"
  fi

  if ! command -v setsid >/dev/null 2>&1; then
    log_error "[${name}] 'setsid' is required to manage process groups"
    return 2
  fi

  : >>"${log_file}"
  (
    cd "${ROOT_DIR}"
    export PYTHONUNBUFFERED=1
    nohup setsid "$@" >>"${log_file}" 2>&1 &
    echo $! >"${pid_file}"
  )

  local new_pid
  new_pid="$(read_pid "${pid_file}")"
  log_ok "[${name}] started (pid/pgid=${new_pid}) log=$(realpath --relative-to="${ROOT_DIR}" "${log_file}" 2>/dev/null || echo "${log_file}")"
}

stop_bg() {
  local name="$1"
  local pid_file="$2"

  local pid=""
  if ! pid="$(read_pid "${pid_file}" 2>/dev/null || true)"; then
    log_info "[${name}] not running (no pid file)"
    return 0
  fi

  if ! pid_running "${pid}"; then
    rm -f "${pid_file}"
    log_info "[${name}] not running (stale pid=${pid})"
    return 0
  fi

  kill -TERM -- "-${pid}" >/dev/null 2>&1 || true

  local i
  for i in {1..50}; do
    if ! pid_running "${pid}"; then
      rm -f "${pid_file}"
      log_ok "[${name}] stopped"
      return 0
    fi
    sleep 0.2
  done

  kill -KILL -- "-${pid}" >/dev/null 2>&1 || true
  rm -f "${pid_file}"
  log_warn "[${name}] killed (timeout)"
}

status_bg() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"

  local pid=""
  if ! pid="$(read_pid "${pid_file}" 2>/dev/null || true)"; then
    log_info "[${name}] stopped"
    return 0
  fi
  if pid_running "${pid}"; then
    log_ok "[${name}] running (pid/pgid=${pid}) log=$(realpath --relative-to="${ROOT_DIR}" "${log_file}" 2>/dev/null || echo "${log_file}")"
  else
    log_warn "[${name}] stopped (stale pid=${pid})"
  fi
}

start_api() {
  local api_port="$1"
  start_bg "api" "${API_PID}" "${API_LOG}" \
    uv run --project apps/api --directory apps/api \
    uvicorn main:app --reload --port "${api_port}"
}

start_worker() {
  start_bg "worker" "${WORKER_PID}" "${WORKER_LOG}" \
    env CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}" \
    TORCH_HOME="${ROOT_DIR}/models/torch" \
    XDG_CACHE_HOME="${ROOT_DIR}/models/cache" \
    HF_HOME="${ROOT_DIR}/models/hf" \
    uv run --project apps/worker --directory apps/worker \
    python main.py
}

start_web() {
  local web_port="$1"
  start_bg "web" "${WEB_PID}" "${WEB_LOG}" \
    bash -lc "cd \"${ROOT_DIR}/apps/web\" && npm run dev -- --port \"${web_port}\""
}

stop_api() { stop_bg "api" "${API_PID}"; }
stop_worker() { stop_bg "worker" "${WORKER_PID}"; }
stop_web() { stop_bg "web" "${WEB_PID}"; }

status_api() { status_bg "api" "${API_PID}" "${API_LOG}"; }
status_worker() { status_bg "worker" "${WORKER_PID}" "${WORKER_LOG}"; }
status_web() { status_bg "web" "${WEB_PID}" "${WEB_LOG}"; }

clean_logs() {
  local services=("$@")
  ensure_log_dir
  for s in "${services[@]}"; do
    case "${s}" in
      api)
        [[ -f "${API_LOG}" ]] && : > "${API_LOG}" && log_info "[api] log cleaned"
        ;;
      worker)
        [[ -f "${WORKER_LOG}" ]] && : > "${WORKER_LOG}" && log_info "[worker] log cleaned"
        ;;
      web)
        [[ -f "${WEB_LOG}" ]] && : > "${WEB_LOG}" && log_info "[web] log cleaned"
        ;;
    esac
  done
}

logs_cmd() {
  local service="$1"
  local follow="${2}"
  local lines="${3}"

  local log_file=""
  case "${service}" in
    api) log_file="${API_LOG}" ;;
    worker) log_file="${WORKER_LOG}" ;;
    web) log_file="${WEB_LOG}" ;;
    *)
      log_error "Unknown service for logs: ${service}"
      return 2
      ;;
  esac

  ensure_log_dir
  : >>"${log_file}"

  if [[ "${follow}" == "true" ]]; then
    tail -f "${log_file}"
  else
    tail -n "${lines}" "${log_file}"
  fi
}

check_env() {
  local missing=()

  command -v uv >/dev/null 2>&1 || missing+=("uv")
  command -v setsid >/dev/null 2>&1 || missing+=("setsid")
  command -v nohup >/dev/null 2>&1 || missing+=("nohup")

  if [[ ${#missing[@]} -gt 0 ]]; then
    log_error "Missing dependencies: ${missing[*]}"
    return 1
  fi

  if [[ ! -f "${ROOT_DIR}/.env" ]]; then
    log_warn ".env not found, using defaults (see .env.example)"
  fi

  log_ok "Environment looks good"
  return 0
}

health_cmd() {
  local api_port="$1"
  local web_port="$2"
  local services=("${@:3}")

  command -v curl >/dev/null 2>&1 || {
    log_error "Missing dependency: curl"
    return 1
  }

  for s in "${services[@]}"; do
    case "${s}" in
      api)
        if curl -sf "http://localhost:${api_port}/health" >/dev/null 2>&1; then
          log_ok "[api] healthy"
        else
          log_error "[api] not responding: http://localhost:${api_port}/health"
        fi
        ;;
      web)
        if curl -sf "http://localhost:${web_port}/" >/dev/null 2>&1; then
          log_ok "[web] healthy"
        else
          log_error "[web] not responding: http://localhost:${web_port}/"
        fi
        ;;
      worker)
        local pid=""
        if pid="$(read_pid "${WORKER_PID}" 2>/dev/null || true)" && [[ -n "${pid}" ]] && pid_running "${pid}"; then
          log_ok "[worker] running (pid/pgid=${pid})"
        else
          log_error "[worker] not running"
        fi
        ;;
    esac
  done
}

main() {
  if [[ $# -lt 1 ]]; then
    usage
    exit 2
  fi

  local cmd="$1"
  shift

  local api_port="${API_PORT_DEFAULT}"
  local web_port="${WEB_PORT_DEFAULT}"
  local follow="false"
  local lines="${LOG_LINES_DEFAULT}"
  local services=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      api|worker|web)
        services+=("$1")
        shift
        ;;
      --api-port)
        api_port="$2"
        shift 2
        ;;
      --web-port)
        web_port="$2"
        shift 2
        ;;
      -f|--follow)
        follow="true"
        shift
        ;;
      -n|--lines)
        lines="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        log_error "Unknown argument: $1"
        usage
        exit 2
        ;;
    esac
  done

  if [[ ${#services[@]} -eq 0 ]]; then
    services=(api worker web)
  fi

  case "${cmd}" in
    up)
      # Stop any running services first and clean logs
      for ((i=${#services[@]}-1; i>=0; i--)); do
        case "${services[$i]}" in
          api) stop_api ;;
          worker) stop_worker ;;
          web) stop_web ;;
        esac
      done
      clean_logs "${services[@]}"
      check_env
      for s in "${services[@]}"; do
        case "${s}" in
          api) start_api "${api_port}" ;;
          worker) start_worker ;;
          web) start_web "${web_port}" ;;
        esac
      done
      ;;
    down)
      for ((i=${#services[@]}-1; i>=0; i--)); do
        case "${services[$i]}" in
          api) stop_api ;;
          worker) stop_worker ;;
          web) stop_web ;;
        esac
      done
      clean_logs "${services[@]}"
      ;;
    restart)
      "${BASH_SOURCE[0]}" down "${services[@]}" --api-port "${api_port}" --web-port "${web_port}"
      "${BASH_SOURCE[0]}" up "${services[@]}" --api-port "${api_port}" --web-port "${web_port}"
      ;;
    status)
      for s in "${services[@]}"; do
        case "${s}" in
          api) status_api ;;
          worker) status_worker ;;
          web) status_web ;;
        esac
      done
      ;;
    logs)
      if [[ ${#services[@]} -ne 1 ]]; then
        log_error "logs command requires exactly one service: api|worker|web"
        usage
        exit 2
      fi
      logs_cmd "${services[0]}" "${follow}" "${lines}"
      ;;
    check)
      check_env
      if [[ " ${services[*]} " == *" web "* ]]; then
        command -v node >/dev/null 2>&1 || log_warn "node not found (required for web)"
        command -v npm >/dev/null 2>&1 || log_warn "npm not found (required for web)"
      fi
      ;;
    health)
      health_cmd "${api_port}" "${web_port}" "${services[@]}"
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
