#!/usr/bin/env python3

# SPDX-FileCopyrightText: © 2022 Decompollaborate
# SPDX-License-Identifier: MIT

from __future__ import annotations

from . import InstructionId, InstructionBase
from .MipsInstructionConfig import InstructionConfig


class InstructionCoprocessor0(InstructionBase):
    Cop0Opcodes_ByFormat = {
        0b00_000: InstructionId.MFC0,
        0b00_001: InstructionId.DMFC0,
        0b00_010: InstructionId.CFC0,
        # 0b00_011: "",
        0b00_100: InstructionId.MTC0,
        0b00_101: InstructionId.DMTC0,
        0b00_110: InstructionId.CTC0,
        # 0b00_111: "",
    }
    Cop0Opcodes_ByFunction = {
        0b000_001: InstructionId.TLBR,
        0b000_010: InstructionId.TLBWI,
        0b000_110: InstructionId.TLBWR,
        0b001_000: InstructionId.TLBP,
        0b011_000: InstructionId.ERET,
    }

    def __init__(self, instr: int):
        super().__init__(instr)

        # self.opcodesDict = 
        self.processUniqueId()


    def processUniqueId(self):
        super().processUniqueId()

        if self.fmt in InstructionCoprocessor0.Cop0Opcodes_ByFormat:
            self.uniqueId = InstructionCoprocessor0.Cop0Opcodes_ByFormat[self.fmt]
        elif self.fmt == 0b01_000: # fmt = BC
            if self.tf:
                if self.nd:
                    self.uniqueId = InstructionId.BC0TL
                else:
                    self.uniqueId = InstructionId.BC0T
            else:
                if self.nd:
                    self.uniqueId = InstructionId.BC0FL
                else:
                    self.uniqueId = InstructionId.BC0F
        elif self.function in InstructionCoprocessor0.Cop0Opcodes_ByFunction:
            self.uniqueId = InstructionCoprocessor0.Cop0Opcodes_ByFunction[self.function]

    def isBranch(self) -> bool:
        if self.uniqueId in (InstructionId.BC0T, InstructionId.BC0TL, InstructionId.BC0F, InstructionId.BC0FL):
            return True
        return False
    def isBranchLikely(self) -> bool:
        if self.uniqueId in (InstructionId.BC0TL, InstructionId.BC0FL):
            return True
        return False


    def modifiesRt(self) -> bool:
        if self.isBranch():
            return False
        if self.uniqueId in (InstructionId.MFC0, InstructionId.DMFC0, InstructionId.CFC0):
            return True
        # TODO
        return super().modifiesRt()
    def modifiesRd(self) -> bool:
        # modifying fs shouldn't be the same as modifying rd
        #if self.uniqueId in (InstructionId.MTC0, InstructionId.DMTC0, InstructionId.CTC0):
        #    return True
        # TODO
        return super().modifiesRd()


    def blankOut(self):
        if self.fmt in InstructionCoprocessor0.Cop0Opcodes_ByFormat:
            self.rt = 0
            self.rd = 0
            self.sa = 0
            self.function = 0
        elif self.fmt == 0b01_000:
            self.rd = 0
            self.sa = 0
            self.function = 0
        elif self.function in InstructionCoprocessor0.Cop0Opcodes_ByFunction:
            self.rt = 0
            self.rd = 0
            self.sa = 0

    def getOpcodeName(self) -> str:
        if not self.isImplemented():
            return f"COP0(0x{self.function:02X})"
        return super().getOpcodeName()


    def disassembleInstruction(self, immOverride: str|None=None) -> str:
        opcode = self.getOpcodeName()
        formated_opcode = opcode.lower().ljust(InstructionConfig.OPCODE_LJUST + self.extraLjustWidthOpcode, ' ')
        rt = self.getRegisterName(self.rt)
        rd = self.getCop0RegisterName(self.rd)
        immediate = hex(self.immediate)
        if immOverride is not None:
            immediate = immOverride

        if self.fmt in InstructionCoprocessor0.Cop0Opcodes_ByFormat:
            result = f"{formated_opcode} {rt},"
            result = result.ljust(14, ' ')
            result += f" {rd}"
            return result

        if self.isBranch():
            result = formated_opcode
            return f"{result} {immediate}"

        if self.function in InstructionCoprocessor0.Cop0Opcodes_ByFunction:
            result = f"{opcode.lower()}"
            return result

        return f"{formated_opcode} 0x{self.instr_index:07X}"