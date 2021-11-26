#!/usr/bin/python3

from __future__ import annotations

from .Utils import *
from .GlobalConfig import GlobalConfig
from .Instructions import InstructionBase, InstructionId
from .MipsContext import Context, ContextSymbol

class Function:
    def __init__(self, name: str, instructions: List[InstructionBase], context: Context, inFileOffset: int, vram: int = -1):
        self.name: str = name
        self.instructions: List[InstructionBase] = list(instructions)
        self.context: Context = context
        self.inFileOffset: int = inFileOffset
        self.commentOffset: int = 0
        self.vram: int = vram
        self.index: int = -1
        self.pointersRemoved: bool = False

        self.localLabels: Dict[int, str] = dict()
        # TODO: this needs a better name
        self.pointersPerInstruction: Dict[int, int] = dict()
        self.constantsPerInstruction: Dict[int, int] = dict()
        self.branchInstructions: List[int] = list()

        self.pointersOffsets: List[int] = list()

        self.referencedVRams: Set[int] = set()
        self.referencedConstants: Set[int] = set()

        self.hasUnimplementedIntrs: bool = False

        self.parent: Any = None

    @property
    def nInstr(self) -> int:
        return len(self.instructions)


    def _processSymbol(self, luiInstr: InstructionBase, luiOffset: int, lowerInstr: InstructionBase, lowerOffset: int) -> int:
        upperHalf = luiInstr.immediate << 16
        lowerHalf = from2Complement(lowerInstr.immediate, 16)
        address = upperHalf + lowerHalf
        self.referencedVRams.add(address)
        if self.context.getGenericSymbol(address) is None:
            if GlobalConfig.ADD_NEW_SYMBOLS:
                contextSym = ContextSymbol(address, "D_" + toHex(address, 8)[2:])
                if lowerInstr.isFloatInstruction():
                    if lowerInstr.isDoubleFloatInstruction():
                        contextSym.type = "f64"
                    else:
                        contextSym.type = "f32"
                if self.parent.newStuffSuffix:
                    if address >= self.vram:
                        contextSym.name += f"_{self.parent.newStuffSuffix}"
                self.context.symbols[address] = contextSym

        if lowerOffset not in self.pointersPerInstruction:
            self.pointersPerInstruction[lowerOffset] = address
        if luiOffset not in self.pointersPerInstruction:
            self.pointersPerInstruction[luiOffset] = address

        return address

    def analyze(self):
        if not GlobalConfig.DISASSEMBLE_UNKNOWN_INSTRUCTIONS and self.hasUnimplementedIntrs:
            if self.vram > -1 and self.context is not None:
                offset = 0
                for instr in self.instructions:
                    currentVram = self.vram + offset
                    contextSym = self.context.getSymbol(currentVram, False)
                    if contextSym is not None:
                        contextSym.isDefined = True

                    offset += 4
            return

        trackedRegisters: Dict[int, int] = dict()
        trackedRegistersAll: Dict[int, int] = dict()
        registersValues: Dict[int, int] = dict()

        instructionOffset = 0
        for instr in self.instructions:
            isLui = False

            if not GlobalConfig.DISASSEMBLE_UNKNOWN_INSTRUCTIONS and not instr.isImplemented():
                # Abort analysis
                self.hasUnimplementedIntrs = True
                return

            if instr.isBranch():
                diff = from2Complement(instr.immediate, 16)
                branch = instructionOffset + diff*4 + 1*4
                if self.vram >= 0:
                    self.referencedVRams.add(self.vram + branch)
                    auxLabel = self.context.getGenericLabel(self.vram + branch)
                    if auxLabel is not None:
                        label = auxLabel
                    else:
                        label = ".L" + toHex(self.vram + branch, 5)[2:]
                else:
                    label = ".L" + toHex(self.inFileOffset + branch, 5)[2:]

                self.localLabels[self.inFileOffset + branch] = label
                if self.vram >= 0:
                    self.context.addBranchLabel(self.vram + branch, label)
                self.branchInstructions.append(instructionOffset)

            elif instr.isJType():
                target = 0x80000000 | instr.instr_index << 2
                if instr.uniqueId == InstructionId.J:
                    self.context.addFakeFunction(target, "fakefunc_" + toHex(target, 8)[2:])
                else:
                    self.context.addFunction(None, target, "func_" + toHex(target, 8)[2:])
                self.pointersPerInstruction[instructionOffset] = target

            # symbol finder
            elif instr.isIType():
                # TODO: Consider following branches
                isLui = instr.uniqueId == InstructionId.LUI
                lastInstr = self.instructions[instructionOffset//4 - 1]
                if isLui:
                    if instr.immediate >= 0x4000: # filter out stuff that may not be a real symbol
                        if lastInstr.isBranch():
                            # If the previous instructions is a branch, do a
                            # look-ahead and check the branch target for possible pointers
                            diff = from2Complement(lastInstr.immediate, 16)
                            branch = instructionOffset + diff*4
                            if branch > 0:
                                targetInstr = self.instructions[branch//4]
                                if targetInstr.uniqueId == InstructionId.JR and targetInstr.getRegisterName(targetInstr.rs) == "$ra":
                                    # If the target instruction is a JR $ra, then look up its delay slot instead
                                    targetInstr = self.instructions[branch//4 + 1]
                                if targetInstr.isIType() and targetInstr.rs == instr.rt:
                                    if targetInstr.uniqueId not in (InstructionId.LUI, InstructionId.ANDI, InstructionId.ORI, InstructionId.XORI, InstructionId.CACHE):
                                        self._processSymbol(instr, instructionOffset, targetInstr, branch)

                                if not (lastInstr.isBranchLikely() or lastInstr.uniqueId == InstructionId.B):
                                    # If the previous instructions is a branch likely, then nulify 
                                    # the effects of this instruction for future analysis
                                    trackedRegisters[instr.rt] = instructionOffset//4
                        else:
                            trackedRegisters[instr.rt] = instructionOffset//4
                    trackedRegistersAll[instr.rt] = instructionOffset//4
                else:
                    if instr.uniqueId == InstructionId.ORI:
                        # Constants
                        rs = instr.rs
                        if rs in trackedRegistersAll:
                            luiInstr = self.instructions[trackedRegistersAll[rs]]
                            upperHalf = luiInstr.immediate << 16
                            lowerHalf = instr.immediate
                            constant = upperHalf | lowerHalf
                            self.referencedConstants.add(constant)
                            self.constantsPerInstruction[instructionOffset] = constant
                            self.constantsPerInstruction[trackedRegistersAll[rs]*4] = constant
                            registersValues[instr.rt] = constant
                    elif instr.uniqueId not in (InstructionId.ANDI, InstructionId.XORI, InstructionId.CACHE):
                        rs = instr.rs
                        if rs in trackedRegisters:
                            luiInstr = self.instructions[trackedRegisters[rs]]
                            address = self._processSymbol(luiInstr, trackedRegisters[rs]*4, instr, instructionOffset)
                            registersValues[instr.rt] = address

            elif instr.uniqueId == InstructionId.JR:
                rs = instr.rs
                if instr.getRegisterName(rs) != "$ra":
                    if rs in registersValues:
                        address = registersValues[rs]
                        self.referencedVRams.add(address)
                        self.context.addJumpTable(address, "jtbl_" + toHex(address, 8)[2:])

            if not instr.isFloatInstruction():
                if not isLui and instr.modifiesRt():
                    rt = instr.rt
                    if rt in trackedRegisters:
                        del trackedRegisters[rt]
                    if rt in trackedRegistersAll:
                        del trackedRegistersAll[rt]

                if instr.modifiesRd():
                    # Usually array offsets use an ADDU to add the index of the array
                    if instr.uniqueId == InstructionId.ADDU:
                        if instr.rd != instr.rs and instr.rd != instr.rt:
                            rd = instr.rd
                            if rd in trackedRegisters:
                                del trackedRegisters[rd]
                            if rd in trackedRegistersAll:
                                del trackedRegistersAll[rd]
                    else:
                        rd = instr.rd
                        if rd in trackedRegisters:
                            del trackedRegisters[rd]
                        if rd in trackedRegistersAll:
                            del trackedRegistersAll[rd]

            else:
                if instr.uniqueId in (InstructionId.MTC1, InstructionId.DMTC1, InstructionId.CTC1):
                    # IDO usually use a register as a temp when loading a constant value
                    # into the float coprocessor, after that IDO never re-uses the value
                    # in that register for anything else
                    rt = instr.rt
                    if rt in trackedRegisters:
                        del trackedRegisters[rt]
                    if rt in trackedRegistersAll:
                        del trackedRegistersAll[rt]

            # look-ahead symbol finder
            lastInstr = self.instructions[instructionOffset//4 - 1]
            if lastInstr.isBranch():
                diff = from2Complement(lastInstr.immediate, 16)
                branch = instructionOffset + diff*4
                if branch > 0 and branch//4 < len(self.instructions):
                    targetInstr = self.instructions[branch//4]
                    if targetInstr.isIType():
                        if targetInstr.uniqueId not in (InstructionId.LUI, InstructionId.ANDI, InstructionId.ORI, InstructionId.XORI, InstructionId.CACHE):
                            rs = targetInstr.rs
                            if rs in trackedRegisters:
                                luiInstr = self.instructions[trackedRegisters[rs]]
                                self._processSymbol(luiInstr, trackedRegisters[rs]*4, targetInstr, branch)

            instructionOffset += 4

    def countDiffOpcodes(self, other: Function) -> int:
        result = 0
        for i in range(min(self.nInstr, other.nInstr)):
            if not self.instructions[i].sameOpcode(other.instructions[i]):
                result += 1
        return result

    def countSameOpcodeButDifferentArguments(self, other: Function) -> int:
        result = 0
        for i in range(min(self.nInstr, other.nInstr)):
            instr1 = self.instructions[i]
            instr2 = other.instructions[i]
            if instr1.sameOpcodeButDifferentArguments(instr2):
                result += 1
        return result

    def blankOutDifferences(self, other_func: Function) -> bool:
        if not GlobalConfig.REMOVE_POINTERS:
            return False

        was_updated = False

        for i in range(min(self.nInstr, other_func.nInstr)):
            instr1 = self.instructions[i]
            instr2 = other_func.instructions[i]
            if instr1.sameOpcodeButDifferentArguments(instr2):
                instr1.blankOut()
                instr2.blankOut()
                was_updated = True

        return was_updated

    def removePointers(self) -> bool:
        if not GlobalConfig.REMOVE_POINTERS:
            return False

        was_updated = False

        for instructionOffset in self.pointersPerInstruction:
            self.instructions[instructionOffset//4].blankOut()
        was_updated = len(self.pointersPerInstruction) > 0 or was_updated

        for fileOffset in self.pointersOffsets:
            index = (fileOffset - self.inFileOffset)//4
            if index < 0:
                continue
            if index >= self.nInstr:
                continue
            self.instructions[index].blankOut()

        if GlobalConfig.IGNORE_BRANCHES:
            for instructionOffset in self.branchInstructions:
                self.instructions[instructionOffset//4].blankOut()
            was_updated = len(self.branchInstructions) > 0 or was_updated

        self.pointersRemoved = True

        return was_updated

    def removeTrailingNops(self) -> bool:
        was_updated = False
        first_nop = self.nInstr

        for i in range(self.nInstr-1, 0-1, -1):
            instr = self.instructions[i]
            if instr.uniqueId != InstructionId.NOP:
                if instr.uniqueId == InstructionId.JR and instr.getRegisterName(instr.rs) == "$ra":
                    first_nop += 1
                break
            first_nop = i

        if first_nop < self.nInstr:
            was_updated = True
            del self.instructions[first_nop:]
        return was_updated

    def disassemble(self) -> str:
        output = ""

        if not GlobalConfig.DISASSEMBLE_UNKNOWN_INSTRUCTIONS:
            if self.hasUnimplementedIntrs:
                return self.disassembleAsData()

        output += f"glabel {self.name}"
        if GlobalConfig.FUNCTION_ASM_COUNT:
            if self.index >= 0:
                output += f" # {self.index}"
        output += "\n"

        wasLastInstABranch = False

        instructionOffset = 0
        auxOffset = self.inFileOffset
        for instr in self.instructions:
            offsetHex = toHex(auxOffset + self.commentOffset, 6)[2:]
            vramHex = ""
            if self.vram >= 0:
                vramHex = toHex(self.vram + instructionOffset, 8)[2:]
            instrHex = toHex(instr.instr, 8)[2:]

            immOverride = None
            if instr.isBranch():
                if not GlobalConfig.IGNORE_BRANCHES:
                    diff = from2Complement(instr.immediate, 16)
                    branch = instructionOffset + diff*4 + 1*4
                    label = self.context.getGenericLabel(self.vram + branch)
                    if self.vram >= 0 and label is not None:
                        immOverride = label
                    elif self.inFileOffset + branch in self.localLabels:
                        immOverride = self.localLabels[self.inFileOffset + branch]

            elif instr.isIType():
                if not self.pointersRemoved and instructionOffset in self.pointersPerInstruction:
                    address = self.pointersPerInstruction[instructionOffset]

                    symbol = self.context.getGenericSymbol(address)
                    if symbol is not None:
                        if instr.uniqueId == InstructionId.LUI:
                            immOverride = f"%hi({symbol})"
                        else:
                            immOverride= f"%lo({symbol})"
                elif instructionOffset in self.constantsPerInstruction:
                    constant = self.constantsPerInstruction[instructionOffset]

                    symbol = self.context.getConstant(constant)
                    if symbol is not None:
                        if instr.uniqueId == InstructionId.LUI:
                            immOverride = f"%hi({symbol})"
                        else:
                            immOverride= f"%lo({symbol})"

            if wasLastInstABranch:
                instr.ljustWidthOpcode -= 1

            line = instr.disassemble(self.context, immOverride)

            if wasLastInstABranch:
                instr.ljustWidthOpcode += 1

            #comment = " "
            comment = ""
            if GlobalConfig.ASM_COMMENT:
                comment = f"/* {offsetHex} {vramHex} {instrHex} */  "
            if wasLastInstABranch:
                comment += " "
            line = comment + line

            label = ""
            if not GlobalConfig.IGNORE_BRANCHES:
                currentVram = self.vram + instructionOffset
                labelAux = self.context.getGenericLabel(currentVram)
                if self.vram >= 0 and labelAux is not None:
                    if self.context.getFunction(currentVram) is not None:
                        # Skip over functions to avoid duplication
                        pass
                    elif currentVram in self.context.jumpTablesLabels:
                        label = "glabel " + labelAux + "\n"
                    else:
                        label = labelAux + ":\n"
                elif auxOffset in self.localLabels:
                    label = self.localLabels[auxOffset] + ":\n"
                elif currentVram in self.context.fakeFunctions:
                    label = self.context.fakeFunctions[currentVram] + ":\n"

            output += label + line + "\n"

            wasLastInstABranch = instr.isBranch() or instr.isJType() or instr.uniqueId in (InstructionId.JR, InstructionId.JALR)

            instructionOffset += 4
            auxOffset += 4

        return output

    def disassembleAsData(self) -> str:
        output = ""

        instructionOffset = 0
        auxOffset = self.inFileOffset
        for instr in self.instructions:
            offsetHex = toHex(auxOffset + self.commentOffset, 6)[2:]
            vramHex = ""
            label = ""
            if self.vram >= 0:
                vramHex = toHex(self.vram + instructionOffset, 8)[2:]
                if self.context is not None:
                    auxLabel = self.context.getGenericLabel(self.vram + instructionOffset) or self.context.getGenericSymbol(self.vram + instructionOffset, tryPlusOffset=False)
                    if auxLabel is not None:
                        label = f"\nglabel {auxLabel}\n"

                    contextVar = self.context.getSymbol(self.vram + instructionOffset, False)
                    if contextVar is not None:
                        contextVar.isDefined = True

            instrHex = toHex(instr.instr, 8)[2:]

            line = f".word  0x{instrHex}"

            #comment = " "
            comment = ""
            if GlobalConfig.ASM_COMMENT:
                comment = f"/* {offsetHex} {vramHex} {instrHex} */  "
            line = comment + line

            output += label + line + "\n"

            instructionOffset += 4
            auxOffset += 4

        return output
