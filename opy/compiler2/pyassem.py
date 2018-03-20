"""A flow graph representation for Python bytecode"""
from __future__ import print_function

import dis
import types

from .consts import CO_OPTIMIZED, CO_NEWLOCALS, CO_VARARGS, CO_VARKEYWORDS


HAS_JREL = set(dis.opname[op] for op in dis.hasjrel)
HAS_JABS = set(dis.opname[op] for op in dis.hasjabs)


OPNUM = dict((name, i) for i, name in enumerate(dis.opname))


def _NameToIndex(name, L):
    """Return index of name in list, appending if necessary

    This routine uses a list instead of a dictionary, because a
    dictionary can't store two different keys if the keys have the
    same value but different types, e.g. 2 and 2L.  The compiler
    must treat these two separately, so it does an explicit type
    comparison before comparing the values.
    """
    t = type(name)
    for i, item in enumerate(L):
        if t == type(item) and item == name:
            return i
    end = len(L)
    L.append(name)
    return end


def ComputeStackDepth(blocks, entry_block, exit_block):
    """Compute the max stack depth.

    Approach is to compute the stack effect of each basic block.
    Then find the path through the code with the largest total
    effect.
    """
    depth = {}
    exit = None
    for b in blocks:
        depth[b] = TRACKER.findDepth(b.getInstructions())

    seen = {}

    def max_depth(b, d):
        if b in seen:
            return d
        seen[b] = 1
        d = d + depth[b]
        children = b.get_children()
        if children:
            return max([max_depth(c, d) for c in children])
        else:
            if not b.label == "exit":
                return max_depth(exit_block, d)
            else:
                return d

    return max_depth(entry_block, 0)


def FlattenGraph(blocks):
    insts = []
    pc = 0
    begin = {}
    end = {}
    for b in blocks:
        begin[b] = pc
        for inst in b.getInstructions():
            insts.append(inst)
            if len(inst) == 1:
                pc = pc + 1
            elif inst[0] != "SET_LINENO":
                # arg takes 2 bytes
                pc = pc + 3
        end[b] = pc
    pc = 0
    for i, inst in enumerate(insts):
        if len(inst) == 1:
            pc = pc + 1
        elif inst[0] != "SET_LINENO":
            pc = pc + 3
        opname = inst[0]
        if opname in HAS_JREL:
            oparg = inst[1]
            offset = begin[oparg] - pc
            insts[i] = opname, offset
        elif opname in HAS_JABS:
            insts[i] = opname, begin[inst[1]]
    return insts


def Assemble(insts):
    ass = Assembler()
    for t in insts:
        opname = t[0]
        if len(t) == 1:
            ass.addCode(OPNUM[opname])
        else:
            oparg = t[1]
            if opname == "SET_LINENO":
                ass.nextLine(oparg)
                continue
            hi, lo = divmod(oparg, 256)
            try:
                ass.addCode(OPNUM[opname], lo, hi)
            except ValueError:
                print(opname, oparg)
                print(OPNUM[opname], lo, hi)
                raise
    return ass


class FlowGraph(object):

    def __init__(self):
        self.current = self.entry = Block()
        self.exit = Block("exit")
        self.blocks = set()
        self.blocks.add(self.entry)
        self.blocks.add(self.exit)

    DEBUG = False

    def startBlock(self, block):
        if self.DEBUG:
            if self.current:
                print("end", repr(self.current))
                print("    next", self.current.next)
                print("    prev", self.current.prev)
                print("   ", self.current.get_children())
            print(repr(block))
        self.current = block

    def nextBlock(self, block=None):
        # XXX think we need to specify when there is implicit transfer
        # from one block to the next.  might be better to represent this
        # with explicit JUMP_ABSOLUTE instructions that are optimized
        # out when they are unnecessary.
        #
        # I think this strategy works: each block has a child
        # designated as "next" which is returned as the last of the
        # children.  because the nodes in a graph are emitted in
        # reverse post order, the "next" block will always be emitted
        # immediately after its parent.
        # Worry: maintaining this invariant could be tricky
        if block is None:
            block = self.newBlock()

        # Note: If the current block ends with an unconditional control
        # transfer, then it is techically incorrect to add an implicit
        # transfer to the block graph. Doing so results in code generation
        # for unreachable blocks.  That doesn't appear to be very common
        # with Python code and since the built-in compiler doesn't optimize
        # it out we don't either.
        self.current.addNext(block)
        self.startBlock(block)

    def newBlock(self):
        b = Block()
        self.blocks.add(b)
        return b

    def startExitBlock(self):
        self.startBlock(self.exit)

    def emit(self, *inst):
        if self.DEBUG:
            print("\t", inst)
        if len(inst) == 2 and isinstance(inst[1], Block):
            self.current.addOutEdge(inst[1])
        self.current.emit(inst)

    def getContainedGraphs(self):
        raise AssertionError('unused')
        l = []
        for b in self.getBlocks():
            l.extend(b.getContainedGraphs())
        return l


def OrderBlocks(start_block, exit_block):
    """Order blocks so that they are emitted in the right order"""
    # Rules:
    # - when a block has a next block, the next block must be emitted just after
    # - when a block has followers (relative jumps), it must be emitted before
    #   them
    # - all reachable blocks must be emitted
    order = []

    # Find all the blocks to be emitted.
    remaining = set()
    todo = [start_block]
    while todo:
        b = todo.pop()
        if b in remaining:
            continue
        remaining.add(b)
        for c in b.get_children():
            if c not in remaining:
                todo.append(c)

    # A block is dominated by another block if that block must be emitted
    # before it.
    dominators = {}
    for b in remaining:
        if __debug__ and b.next:
            assert b is b.next[0].prev[0], (b, b.next)
        # Make sure every block appears in dominators, even if no
        # other block must precede it.
        dominators.setdefault(b, set())
        # preceding blocks dominate following blocks
        for c in b.get_followers():
            while 1:
                dominators.setdefault(c, set()).add(b)
                # Any block that has a next pointer leading to c is also
                # dominated because the whole chain will be emitted at once.
                # Walk backwards and add them all.
                if c.prev and c.prev[0] is not b:
                    c = c.prev[0]
                else:
                    break

    def find_next():
        # Find a block that can be emitted next.
        for b in remaining:
            for c in dominators[b]:
                if c in remaining:
                    break # can't emit yet, dominated by a remaining block
            else:
                return b
        assert 0, 'circular dependency, cannot find next block'

    b = start_block
    while 1:
        order.append(b)
        remaining.discard(b)
        if b.next:
            b = b.next[0]
            continue
        elif b is not exit_block and not b.has_unconditional_transfer():
            order.append(exit_block)
        if not remaining:
            break
        b = find_next()
    return order


gBlockCounter = 0


class Block(object):

    def __init__(self, label=''):
        self.label = label

        global gBlockCounter
        self.bid = gBlockCounter
        gBlockCounter += 1

        self.insts = []
        self.outEdges = set()
        self.next = []
        self.prev = []

    # BUG FIX: This is needed for deterministic order in sets (and dicts?).
    # See OrderBlocks() below.  remaining is set() of blocks.  If we rely on
    # the default id(), then the output bytecode is NONDETERMINISTIC.
    def __hash__(self):
        return self.bid

    def __repr__(self):
        if self.label:
            return "<block %s id=%d>" % (self.label, self.bid)
        else:
            return "<block id=%d>" % (self.bid)

    def __str__(self):
        return "<block %s %d:\n%s>" % (
            self.label, self.bid,
            '\n'.join(str(inst) for inst in self.insts))

    def emit(self, inst):
        op = inst[0]
        self.insts.append(inst)

    def getInstructions(self):
        return self.insts

    def addOutEdge(self, block):
        self.outEdges.add(block)

    def addNext(self, block):
        self.next.append(block)
        assert len(self.next) == 1, [str(b) for b in self.next]
        block.prev.append(self)
        assert len(block.prev) == 1, [str(b) for b in block.prev]

    _uncond_transfer = ('RETURN_VALUE', 'RAISE_VARARGS',
                        'JUMP_ABSOLUTE', 'JUMP_FORWARD', 'CONTINUE_LOOP',
                        )

    def has_unconditional_transfer(self):
        """Returns True if there is an unconditional transfer to an other block
        at the end of this block. This means there is no risk for the bytecode
        executer to go past this block's bytecode."""
        try:
            op, arg = self.insts[-1]
        except (IndexError, ValueError):
            return
        return op in self._uncond_transfer

    def get_children(self):
        return list(self.outEdges) + self.next

    def get_followers(self):
        """Get the whole list of followers, including the next block."""
        followers = set(self.next)
        # Blocks that must be emitted *after* this one, because of
        # bytecode offsets (e.g. relative jumps) pointing to them.
        for inst in self.insts:
            if inst[0] in HAS_JREL:
                followers.add(inst[1])
        return followers

    def getContainedGraphs(self):
        """Return all graphs contained within this block.

        For example, a MAKE_FUNCTION block will contain a reference to
        the graph for the function body.
        """
        raise AssertionError('unused')
        contained = []
        for inst in self.insts:
            if len(inst) == 1:
                continue
            op = inst[1]
            if hasattr(op, 'graph'):
                contained.append(op.graph)
        return contained


class PyFlowGraph(FlowGraph):
    """Something that gets turned into a single code object.

    Code objects and consts are mutually recursive.

    Instantiated by compile() (3 cases), and by AbstractFunctionCode and
    AbstractClassCode.

    TODO: Separate FlowGraph from PyFlowGraph.
    Make a function

    code_object = Assemble(flow_graph)
    """

    def __init__(self, name, filename, optimized=0, klass=None):
        """
        Args:
          klass: Whether we're compiling a class block.
        """
        FlowGraph.__init__(self)

        self.name = name  # name that is put in the code object
        self.filename = filename
        self.docstring = None
        self.klass = klass
        if optimized:
            self.flags = CO_OPTIMIZED | CO_NEWLOCALS
        else:
            self.flags = 0

        # TODO: All of these go in the code object.  Might want to separate
        # them.  CodeContext.
        self.consts = []
        self.names = []
        # Free variables found by the symbol table scan, including
        # variables used only in nested scopes, are included here.
        self.freevars = []
        self.cellvars = []
        # The closure list is used to track the order of cell
        # variables and free variables in the resulting code object.
        # The offsets used by LOAD_CLOSURE/LOAD_DEREF refer to both
        # kinds of variables.
        self.closure = []

        # Mutated by setArgs()
        self.varnames = []
        self.argcount = 0

    # TODO: setArgs, setFreeVars, setCellVars can be done in constructor.  The
    # scope is available.

    def setArgs(self, args):
        """Only called by functions, not modules or classes."""
        assert not self.varnames   # Nothing should have been added
        if args:
            self.varnames = list(args)
            self.argcount = len(args)

    def setFreeVars(self, names):
        self.freevars = list(names)

    def setCellVars(self, names):
        self.cellvars = names

    def setDocstring(self, doc):
        self.docstring = doc

    def setFlag(self, flag):
        self.flags = self.flags | flag
        if flag == CO_VARARGS:
            self.argcount -= 1

    def checkFlag(self, flag):
        if self.flags & flag:
            return 1

    def MakeCodeObject(self):
        """Assemble a Python code object."""
        # TODO: Split into two representations?  Graph and insts?
        # Do we need a shared varnames representation?

        stacksize = ComputeStackDepth(self.blocks, self.entry, self.exit)
        blocks = OrderBlocks(self.entry, self.exit)
        insts = FlattenGraph(blocks)

        self.consts.insert(0, self.docstring)

        # Rearrange self.cellvars so the ones in self.varnames are first.
        # And prune from freevars (?)
        lookup = set(self.cellvars)
        remaining = lookup - set(self.varnames)

        self.cellvars = [n for n in self.varnames if n in lookup]
        self.cellvars.extend(remaining)

        self.closure = self.cellvars + self.freevars

        # Convert arguments from symbolic to concrete form
        # Mutates the insts argument.  The converters mutate self.names,
        # self.varnames, etc.
        enc = ArgEncoder(self.klass, self.consts, self.names, self.varnames,
                         self.closure)

        for i, t in enumerate(insts):
            if len(t) == 2:
                opname, oparg = t
                method = enc.Get(opname)
                if method:
                    insts[i] = opname, method(enc, oparg)

        ass = Assemble(insts)

        if (self.flags & CO_NEWLOCALS) == 0:
            nlocals = 0
        else:
            nlocals = len(self.varnames)

        if self.flags & CO_VARKEYWORDS:
            self.argcount -= 1

        return types.CodeType(
            self.argcount, nlocals, stacksize, self.flags,
            ass.Bytecode(),
            tuple(self.consts),
            tuple(self.names),
            tuple(self.varnames),
            self.filename, self.name, ass.firstline,
            ass.LineNumberTable(),
            tuple(self.freevars),
            tuple(self.cellvars))


class ArgEncoder(object):
    """ TODO: This should just be a simple switch ."""

    def __init__(self, klass, consts, names, varnames, closure):
        """
        Args:
          consts ... closure are all potentially mutated!
        """
        self.klass = klass
        self.consts = consts
        self.names = names
        self.varnames = varnames
        self.closure = closure

    def _convert_LOAD_CONST(self, arg):
        from . import pycodegen
        if isinstance(arg, pycodegen.CodeGenerator):
            arg = arg.graph.MakeCodeObject()
        return _NameToIndex(arg, self.consts)

    def _convert_LOAD_FAST(self, arg):
        _NameToIndex(arg, self.names)
        return _NameToIndex(arg, self.varnames)
    _convert_STORE_FAST = _convert_LOAD_FAST
    _convert_DELETE_FAST = _convert_LOAD_FAST

    def _convert_LOAD_NAME(self, arg):
        if self.klass is None:
            _NameToIndex(arg, self.varnames)
        return _NameToIndex(arg, self.names)

    def _convert_NAME(self, arg):
        if self.klass is None:
            _NameToIndex(arg, self.varnames)
        return _NameToIndex(arg, self.names)
    _convert_STORE_NAME = _convert_NAME
    _convert_DELETE_NAME = _convert_NAME
    _convert_IMPORT_NAME = _convert_NAME
    _convert_IMPORT_FROM = _convert_NAME
    _convert_STORE_ATTR = _convert_NAME
    _convert_LOAD_ATTR = _convert_NAME
    _convert_DELETE_ATTR = _convert_NAME
    _convert_LOAD_GLOBAL = _convert_NAME
    _convert_STORE_GLOBAL = _convert_NAME
    _convert_DELETE_GLOBAL = _convert_NAME

    def _convert_DEREF(self, arg):
        _NameToIndex(arg, self.names)
        _NameToIndex(arg, self.varnames)
        return _NameToIndex(arg, self.closure)
    _convert_LOAD_DEREF = _convert_DEREF
    _convert_STORE_DEREF = _convert_DEREF

    def _convert_LOAD_CLOSURE(self, arg):
        _NameToIndex(arg, self.varnames)
        return _NameToIndex(arg, self.closure)

    _cmp = list(dis.cmp_op)
    def _convert_COMPARE_OP(self, arg):
        return self._cmp.index(arg)

    _converters = {}

    # similarly for other opcodes...

    for name, obj in locals().items():
        if name[:9] == "_convert_":
            opname = name[9:]
            _converters[opname] = obj
    del name, obj, opname

    def Get(self, opname):
      return self._converters.get(opname, None)


class Assembler(object):
    """Builds co_code and lnotab.

    This class builds the lnotab, which is documented in compile.c.  Here's a
    brief recap:

    For each SET_LINENO instruction after the first one, two bytes are added to
    lnotab.  (In some cases, multiple two-byte entries are added.)  The first
    byte is the distance in bytes between the instruction for the last
    SET_LINENO and the current SET_LINENO.  The second byte is offset in line
    numbers.  If either offset is greater than 255, multiple two-byte entries
    are added -- see compile.c for the delicate details.
    """
    def __init__(self):
        self.code = []
        self.codeOffset = 0
        self.firstline = 0
        self.lastline = 0
        self.lastoff = 0
        self.lnotab = []

    def addCode(self, *args):
        for arg in args:
            self.code.append(chr(arg))
        self.codeOffset += len(args)

    def nextLine(self, lineno):
        if self.firstline == 0:
            self.firstline = lineno
            self.lastline = lineno
        else:
            # compute deltas
            addr = self.codeOffset - self.lastoff
            line = lineno - self.lastline
            # Python assumes that lineno always increases with
            # increasing bytecode address (lnotab is unsigned char).
            # Depending on when SET_LINENO instructions are emitted
            # this is not always true.  Consider the code:
            #     a = (1,
            #          b)
            # In the bytecode stream, the assignment to "a" occurs
            # after the loading of "b".  This works with the C Python
            # compiler because it only generates a SET_LINENO instruction
            # for the assignment.
            if line >= 0:
                push = self.lnotab.append
                while addr > 255:
                    push(255); push(0)
                    addr -= 255
                while line > 255:
                    push(addr); push(255)
                    line -= 255
                    addr = 0
                if addr > 0 or line > 0:
                    push(addr); push(line)
                self.lastline = lineno
                self.lastoff = self.codeOffset

    def Bytecode(self):
        return ''.join(self.code)

    def LineNumberTable(self):
        return ''.join(chr(c) for c in self.lnotab)


class StackDepthTracker(object):
    # XXX 1. need to keep track of stack depth on jumps
    # XXX 2. at least partly as a result, this code is broken

    def findDepth(self, insts, debug=0):
        depth = 0
        maxDepth = 0
        for i in insts:
            opname = i[0]
            if debug:
                print(i, end=' ')
            delta = self.effect.get(opname, None)
            if delta is not None:
                depth = depth + delta
            else:
                # now check patterns
                for pat, pat_delta in self.patterns:
                    if opname[:len(pat)] == pat:
                        delta = pat_delta
                        depth = depth + delta
                        break
                # if we still haven't found a match
                if delta is None:
                    meth = getattr(self, opname, None)
                    if meth is not None:
                        depth = depth + meth(i[1])
            if depth > maxDepth:
                maxDepth = depth
            if debug:
                print(depth, maxDepth)
        return maxDepth

    effect = {
        'POP_TOP': -1,
        'DUP_TOP': 1,
        'LIST_APPEND': -1,
        'SET_ADD': -1,
        'MAP_ADD': -2,
        'SLICE+1': -1,
        'SLICE+2': -1,
        'SLICE+3': -2,
        'STORE_SLICE+0': -1,
        'STORE_SLICE+1': -2,
        'STORE_SLICE+2': -2,
        'STORE_SLICE+3': -3,
        'DELETE_SLICE+0': -1,
        'DELETE_SLICE+1': -2,
        'DELETE_SLICE+2': -2,
        'DELETE_SLICE+3': -3,
        'STORE_SUBSCR': -3,
        'DELETE_SUBSCR': -2,
        # PRINT_EXPR?
        'PRINT_ITEM': -1,
        'RETURN_VALUE': -1,
        'YIELD_VALUE': -1,
        'EXEC_STMT': -3,
        'BUILD_CLASS': -2,
        'STORE_NAME': -1,
        'STORE_ATTR': -2,
        'DELETE_ATTR': -1,
        'STORE_GLOBAL': -1,
        'BUILD_MAP': 1,
        'COMPARE_OP': -1,
        'STORE_FAST': -1,
        'IMPORT_STAR': -1,
        'IMPORT_NAME': -1,
        'IMPORT_FROM': 1,
        'LOAD_ATTR': 0, # unlike other loads
        # close enough...
        'SETUP_EXCEPT': 3,
        'SETUP_FINALLY': 3,
        'FOR_ITER': 1,
        'WITH_CLEANUP': -1,
        }
    # use pattern match
    patterns = [
        ('BINARY_', -1),
        ('LOAD_', 1),
        ]

    def UNPACK_SEQUENCE(self, count):
        return count-1
    def BUILD_TUPLE(self, count):
        return -count+1
    def BUILD_LIST(self, count):
        return -count+1
    def BUILD_SET(self, count):
        return -count+1
    def CALL_FUNCTION(self, argc):
        hi, lo = divmod(argc, 256)
        return -(lo + hi * 2)
    def CALL_FUNCTION_VAR(self, argc):
        return self.CALL_FUNCTION(argc)-1
    def CALL_FUNCTION_KW(self, argc):
        return self.CALL_FUNCTION(argc)-1
    def CALL_FUNCTION_VAR_KW(self, argc):
        return self.CALL_FUNCTION(argc)-2
    def MAKE_FUNCTION(self, argc):
        return -argc
    def MAKE_CLOSURE(self, argc):
        # XXX need to account for free variables too!
        return -argc
    def BUILD_SLICE(self, argc):
        if argc == 2:
            return -1
        elif argc == 3:
            return -2
    def DUP_TOPX(self, argc):
        return argc


TRACKER = StackDepthTracker()
