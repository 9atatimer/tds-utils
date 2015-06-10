export PS1="\u@\h:\w$ "
export PATH="~/bin:/Applications/Emacs.app/Contents/MacOS/bin:$PATH"
export EDITOR=emacsclient
export HADOOP_HOME=/opt/twitter/Cellar/hadoop/0.20.1/libexec
#export JAVA_HOME="$(/usr/libexec/java_home)"

# from https://confluence.twitter.biz/display/MOBILE/Setting+up+your+environment
# JAVA_HOME is typically /Library/Java/JavaVirtualMachines/jdk1.7.0_17.jdk/Contents/Home
JAVA_HOME="`/usr/libexec/java_home -v '1.7*'`" 
ANDROID_HOME="/Applications/Android Studio.app/sdk"
GRADLE_OPTS="-Xms512m -Xmx1024m"
PATH=$PATH:"$ANDROID_HOME/tools"
PATH=$PATH:"$ANDROID_HOME/platform-tools"
PATH=$PATH:"$ANDROID_HOME/build-tools/19.1.0"
export JAVA_HOME ANDROID_HOME GRADLE_OPTS PATH
launchctl setenv ANDROID_HOME "$ANDROID_HOME"
launchctl setenv GRADLE_OPTS "$GRADLE_OPTS"

_JAVA_OPTIONS="-Xmx2g"
export _JAVA_OPTIONS
launchctl setenv _JAVA_OPTIONS "$_JAVA_OPTIONS"

# dottools: add distribution binary directories to PATH
if [ -r "$HOME/.tools-cache/setup-dottools-path.sh" ]; then
  . "$HOME/.tools-cache/setup-dottools-path.sh"
fi

alias truegit=/usr/bin/git
