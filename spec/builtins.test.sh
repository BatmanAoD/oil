#!/bin/bash

### echo dashes
echo -
echo --
echo ---
# stdout-json: "-\n--\n---\n"

### exec builtin 
exec echo hi
# stdout: hi

### exec builtin with redirects
exec 1>&2
echo 'to stderr'
# stdout-json: ""
# stderr: to stderr

### exec builtin with here doc
# This has in a separate file because both code and data can be read from
# stdin.
$SH spec/exec-here-doc.sh
# stdout-json: "x=one\ny=two\nDONE\n"

### cd and $PWD
cd /
echo $PWD
# stdout: /

### $OLDPWD
cd /
cd $TMP
echo "old: $OLDPWD"
cd -
# stdout-json: "old: /\n/\n"

### pushd/popd
set -o errexit
cd /
pushd $TMP
popd
pwd
# status: 0
# N-I dash/mksh status: 127

### Source
lib=$TMP/spec-test-lib.sh
echo 'LIBVAR=libvar' > $lib
. $lib  # dash doesn't have source
echo $LIBVAR
# stdout: libvar

### Exit builtin
exit 3
# status: 3

### Exit builtin with invalid arg 
exit invalid
# Rationale: runtime errors are 1
# status: 1
# OK dash/bash status: 2

### Exit builtin with too many args
exit 7 8 9
echo "no exit: $?"
# status: 0
# stdout-json: "no exit: 1\n"
# BUG dash status: 7
# BUG dash stdout-json: ""
# OK mksh status: 1
# OK mksh stdout-json: ""

### Export sets a global variable
# Even after you do export -n, it still exists.
f() { export GLOBAL=X; }
f
echo $GLOBAL
printenv.py GLOBAL
# stdout-json: "X\nX\n"

### Export sets a global variable that persists after export -n
f() { export GLOBAL=X; }
f
echo $GLOBAL
printenv.py GLOBAL
export -n GLOBAL
echo $GLOBAL
printenv.py GLOBAL
# stdout-json: "X\nX\nX\nNone\n"
# N-I mksh/dash stdout-json: "X\nX\n"
# N-I mksh status: 1
# N-I dash status: 2

### Export a global variable and unset it
f() { export GLOBAL=X; }
f
echo $GLOBAL
printenv.py GLOBAL
unset GLOBAL
echo $GLOBAL
printenv.py GLOBAL
# stdout-json: "X\nX\n\nNone\n"

### Export existing global variables
G1=g1
G2=g2
export G1 G2
printenv.py G1 G2
# stdout-json: "g1\ng2\n"

### Export existing local variable
f() {
  local L1=local1
  export L1
  printenv.py L1
}
f
printenv.py L1
# stdout-json: "local1\nNone\n"

### Export a local that shadows a global
V=global
f() {
  local V=local1
  export V
  printenv.py V
}
f
printenv.py V  # exported local out of scope; global isn't exported yet
export V
printenv.py V  # now it's exported
# stdout-json: "local1\nNone\nglobal\n"

### Export a variable before defining it
export U
U=u
printenv.py U
# stdout: u

### Exporting a parent func variable (dynamic scope)
# The algorithm is to walk up the stack and export that one.
inner() {
  export outer_var
  echo "inner: $outer_var"
  printenv.py outer_var
}
outer() {
  local outer_var=X
  echo "before inner"
  printenv.py outer_var
  inner
  echo "after inner"
  printenv.py outer_var
}
outer
# stdout-json: "before inner\nNone\ninner: X\nX\nafter inner\nX\n"

### time block
# bash and mksh work; dash does't.
# TODO: osh needs to implement BraceGroup redirect properly.
err=_tmp/time-$(basename $SH).txt
{
  time {
    sleep 0.01
    sleep 0.02
  }
} 2> $err
cat $err | grep --only-matching real
# Just check that we found 'real'.
# This is fiddly:
# | sed -n -E -e 's/.*(0m0\.03).*/\1/'
#
# status: 0
# stdout: real
# BUG dash status: 2
# BUG dash stdout-json: ""

### time pipeline
time echo hi | wc -c
# stdout: 3
# status: 0

### shift
set -- 1 2 3 4
shift
echo "$@"
shift 2
echo "$@"
# stdout-json: "2 3 4\n4\n"
# status: 0

### Shifting too far
set -- 1
shift 2
# status: 1
# OK dash status: 2

### Invalid shift argument
shift ZZZ
# status: 1
# OK dash status: 2
# BUG mksh status: 0

### Read builtin
# NOTE: there are TABS below
read x <<EOF
A		B C D E
FG
EOF
echo "[$x]"
# stdout: [A		B C D E]
# status: 0

### Read builtin with no newline.
# This is odd because the variable is populated successfully.  OSH/Oil might
# need a separate put reading feature that doesn't use IFS.
echo -n ZZZ | { read x; echo $?; echo $x; }
# stdout-json: "1\nZZZ\n"
# status: 0

### Read builtin with multiple variables
# NOTE: there are TABS below
read x y z <<EOF
A		B C D E
FG
EOF
echo "$x/$y/$z"
# stdout: A/B/C D E
# status: 0

### Read builtin with not enough variables
set -o errexit
set -o nounset  # hm this doesn't change it
read x y z <<EOF
A B
EOF
echo /$x/$y/$z/
# stdout: /A/B//
# status: 0

### Unset a variable
foo=bar
echo foo=$foo
unset foo
echo foo=$foo
# stdout-json: "foo=bar\nfoo=\n"

### Unset exit status
V=123
unset V
echo status=$?
# stdout: status=0

### Unset nonexistent variable
unset ZZZ
echo status=$?
# stdout: status=0

### Unset readonly variable
# dash aborts the whole program
readonly R=foo
unset R
echo status=$?
# stdout-json: "status=1\n"
# OK dash status: 2
# OK dash stdout-json: ""

### Unset a function without -f
f() {
  echo foo
}
f
unset f
f
# stdout: foo
# status: 127
# N-I dash/mksh status: 0
# N-I dash/mksh stdout-json: "foo\nfoo\n"

### Unset has dynamic scope
f() {
  unset foo
}
foo=bar
echo foo=$foo
f
echo foo=$foo
# stdout-json: "foo=bar\nfoo=\n"

### Unset -v
foo() {
  echo "function foo"
}
foo=bar
unset -v foo
echo foo=$foo
foo
# stdout-json: "foo=\nfunction foo\n"

### Unset -f
foo() {
  echo "function foo"
}
foo=bar
unset -f foo
echo foo=$foo
foo
echo status=$?
# stdout-json: "foo=bar\nstatus=127\n"
