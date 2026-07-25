#!/usr/bin/env bash
# pre-invocation.sh -- provision agent tooling at session start.

set -euo pipefail

LOGFILE="/tmp/antigravity-hook.log"
echo "--- $(date) ---" >> "$LOGFILE"

# Make sure we have a sane PATH for non-interactive shells
export PATH="/opt/homebrew/bin:$HOME/workplace/tds-utils/bin:$PATH"

# --- Flow functions ---
run_provision() {
    local payload
    payload=$(cat)
    
    echo "Hook invoked." >> "$LOGFILE"
    
    # We need jq to extract invocationNum
    if ! command -v jq >/dev/null 2>&1; then
        echo "jq: not on PATH; skipping session provisioning" >> "$LOGFILE"
        echo '{"injectSteps": []}'
        return 0
    fi
    
    local inv_num
    inv_num=$(echo "$payload" | jq -r '.invocationNum')
    echo "Invocation Num: $inv_num" >> "$LOGFILE"

    if [[ "$inv_num" == "0" ]]; then
        echo "Session start detected. Provisioning..." >> "$LOGFILE"
        
        if command -v clai >/dev/null 2>&1; then
            echo "Running clai provision..." >> "$LOGFILE"
            clai provision --offline-ok >> "$LOGFILE" 2>&1 || true
            
            # Now explicitly execute the agy pre-hooks to enable MCPs, etc.
            local pre_hook_dir="$HOME/workplace/tds-utils/clai.d/agy/pre"
            if [[ -d "$pre_hook_dir" ]]; then
                for hook in "$pre_hook_dir"/*; do
                    if [[ -x "$hook" && ! -d "$hook" ]]; then
                        echo "Executing $hook" >> "$LOGFILE"
                        "$hook" >> "$LOGFILE" 2>&1 || true
                    fi
                done
            fi
        else
            echo "clai: not on PATH; skipping session provisioning" >> "$LOGFILE"
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
