# Executed for each sub-shell -- declare, do not append.

# Don't do this here -- it clogs the PATH
#export PATH="~/bin:/Applications/Emacs.app/Contents/MacOS/bin:$PATH"
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