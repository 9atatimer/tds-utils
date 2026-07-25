#!/bin/zsh
# pre-invocation.sh -- provision agent tooling at session start.

set -euo pipefail

# --- Flow functions ---
run_provision() {
    local payload
    payload=$(cat)
    
    local logfile="${TMPDIR:-/tmp}/antigravity-hook.log"
    echo "--- $(date) ---" >> "$logfile"
    echo "Hook invoked." >> "$logfile"
    
    # We need jq to extract invocationNum
    if ! command -v jq >/dev/null 2>&1; then
        echo "jq: not on PATH; skipping session provisioning" >> "$logfile"
        echo '{"injectSteps": []}'
        return 0
    fi
    
    local inv_num
    inv_num=$(echo "$payload" | jq -r '.invocationNum' 2>/dev/null || echo "1")
    echo "Invocation Num: $inv_num" >> "$logfile"

    if [[ "$inv_num" == "0" ]]; then
        echo "Session start detected. Provisioning..." >> "$logfile"
        
        # Make sure we have a sane PATH for non-interactive shells
        local script_dir="${0:A:h}"
        local repo_dir="$(cd "${script_dir}/../.." && pwd)"
        export PATH="/opt/homebrew/bin:${repo_dir}/bin:$PATH"
        
        if command -v clai >/dev/null 2>&1; then
            echo "Running clai provision..." >> "$logfile"
            clai provision --offline-ok >> "$logfile" 2>&1 || true
            
            # Now explicitly execute the agy pre-hooks to enable MCPs, etc.
            local pre_hook_dir="${script_dir}/pre"
            if [[ -d "$pre_hook_dir" ]]; then
                for hook in "$pre_hook_dir"/*; do
                    if [[ -x "$hook" && ! -d "$hook" ]]; then
                        echo "Executing $hook" >> "$logfile"
                        "$hook" >> "$logfile" 2>&1 || true
                    fi
                done
            fi
        else
            echo "clai: not on PATH; skipping session provisioning" >> "$logfile"
        fi
    fi
    
    # Fulfill the Antigravity hook contract (must return valid JSON)
    echo '{"injectSteps": []}'
}

# --- Main ---
main() {
    run_provision
}

main "$@"
