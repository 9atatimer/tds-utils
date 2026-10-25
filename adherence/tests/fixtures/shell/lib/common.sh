# common.sh -- what the tools source.

log_line() {
    printf '%s\n' "$*" | tee -a "${LOG_FILE:-/dev/null}"
}
