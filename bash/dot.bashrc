# Executed for each sub-shell -- declare, do not append.

# ast-mcp: dynamically resolve AST_MCP_BIN path based on environment if unset
if [ -z "${AST_MCP_BIN:-}" ]; then
  if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
    export AST_MCP_BIN="${CLAUDE_PROJECT_DIR:-$PWD}/.ast-mcp/node_modules/.bin/ast-mcp"
  else
    export AST_MCP_BIN="${HOME}/.local/bin/ast-mcp"
  fi
fi


# Don't do this here -- it clogs the PATH
#export PATH="$HOME/bin:/Applications/Emacs.app/Contents/MacOS/bin:$PATH"
export EDITOR=emacsclient

alias urldecode='python -c "import sys, urllib as ul; \
    print ul.unquote_plus(sys.argv[1])"'

zwget() { ID="`openssl rand -hex 8`"; echo; echo http://go/zipkin/$ID; echo; wget --header "X-B3-SpanId: $ID" --header "X-B3-TraceId: $ID" --header "X-B3-Flags: 1" "$@"; }

ztwurl() { ID="`openssl rand -hex 8`"; echo; echo http://go/zipkin/$ID; echo; twurl -A "X-B3-SpanId: $ID" -A "X-B3-TraceId: $ID" -A "X-B3-Flags: 1" "$@"; }
ztwurl2() { ID="`openssl rand -hex 8`"; echo; echo http://go/zipkin/$ID; echo; twurl2 -A "X-B3-SpanId: $ID" -A "X-B3-TraceId: $ID" -A "X-B3-Flags: 1" "$@"; }

scp () {
    if grep -q ':' <<< "$@"
    then
        /usr/bin/scp $@
    else
        echo "no remote destination" >&2
    fi
}

echo 'dot.bashrc' >> ~/trace.log
