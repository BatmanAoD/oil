#!/bin/bash

### no expansion
echo {foo}
# stdout: {foo}

### expansion
echo {foo,bar}
# stdout: foo bar

### double expansion
echo {a,b}_{c,d}
# stdout: a_c a_d b_c b_d

### triple expansion
echo {0,1}{0,1}{0,1}
# stdout: 000 001 010 011 100 101 110 111

### double expansion with single and double quotes
echo {'a',b}_{c,"d"}
# stdout: a_c a_d b_c b_d

### expansion with simple var
a=A
echo -{$a,b}-
# stdout: -A- -b-

### double expansion with simple var -- bash bug
# bash is inconsistent with the above
a=A
echo {$a,b}_{c,d}
# stdout: A_c A_d b_c b_d
# BUG bash stdout: b_c b_d

### double expansion with braced variable
# This fixes it
a=A
echo {${a},b}_{c,d}
# stdout: A_c A_d b_c b_d

### double expansion with literal and simple var
a=A
echo {_$a,b}_{c,d}
# stdout: _A_c _A_d b_c b_d
# BUG bash stdout: _ _ b_c b_d

### expansion with command sub
a=A
echo -{$(echo a),b}-
# stdout: -a- -b-

### expansion with arith sub
a=A
echo -{$((1 + 2)),b}-
# stdout: -3- -b-

### double expansion with escaped literals
a=A
echo -{\$,\[,\]}-
# stdout: -$- -[- -]-

### { in expansion
# bash and mksh treat this differently.  bash treats the
# first { is a prefix.  I think it's harder to read, and \{{a,b} should be
# required.
echo {{a,b}
# stdout: {{a,b}
# BUG bash stdout: {a {b

### quoted { in expansion
echo \{{a,b}
# stdout: {a {b

### } in expansion
# hm they treat this the SAME.  Leftmost { is matched by first }, and then
# there is another } as the postfix.
echo {a,b}}
# stdout: a} b}

### Empty expansion
echo a{X,,Y}b
# stdout: aXb ab aYb

### nested brace expansion
echo -{A,={a,b}=,B}-
# stdout: -A- -=a=- -=b=- -B-

### triple nested brace expansion
echo -{A,={a,.{x,y}.,b}=,B}-
# stdout: -A- -=a=- -=.x.=- -=.y.=- -=b=- -B-

### expansion on RHS of assignment
# I think bash's behavior is more consistent.  No splitting either.
v={X,Y}
echo $v
# stdout: {X,Y}
# BUG mksh stdout: X Y

### no expansion with RHS assignment
{v,x}=X
# status: 127

### Tilde expansion
HOME=/home/foo
echo ~
HOME=/home/bar
echo ~
# stdout-json: "/home/foo\n/home/bar\n"

### Tilde expansion with brace expansion
# The brace expansion happens FIRST.  After that, the second token has tilde
# FIRST, so it gets expanded.  The first token has an unexpanded tilde, because
# it's not in the leading position.
# NOTE: mksh gives different behavior!  So it probably doesn't matter that
# much...
HOME=/home/bob
echo {foo~,~}/bar
# stdout: foo~/bar /home/bob/bar
# OK mksh stdout: foo~/bar ~/bar

### Two kinds of tilde expansion
# ~/foo and ~bar
HOME=/home/bob
echo ~{/src,root}
# stdout: /home/bob/src /root
# OK mksh stdout: ~/src ~root

### Tilde expansion come before var expansion
HOME=/home/bob
foo=~
echo $foo
foo='~'
echo $foo
# In the second instance, we expand into a literal ~, and since var expansion
# comes after tilde expansion, it is NOT tried again.
# stdout-json: "/home/bob\n~\n"

### Number expansion
echo -{1..8..3}-
# stdout: -1- -4- -7-
# N-I mksh stdout: -{1..8..3}-
