#!/usr/bin/env python3

# SPDX-FileCopyrightText: © 2022 Decompollaborate
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Callable

from ... import common


class SymbolBase(common.ElementBase):
    def __init__(self, context: common.Context, vromStart: int, vromEnd: int, inFileOffset: int, vram: int, words: list[int], sectionType: common.FileSectionType, segmentVromStart: int, overlayCategory: str|None):
        super().__init__(context, vromStart, vromEnd, inFileOffset, vram, "", words, sectionType, segmentVromStart, overlayCategory)

        self.endOfLineComment: list[str] = []

        contextSym = self.addSymbol(self.vram, sectionType=self.sectionType, isAutogenerated=True)
        contextSym.vromAddress = self.vromStart
        contextSym.isDefined = True
        contextSym.sectionType = self.sectionType
        self.contextSym: common.ContextSymbol = contextSym


    def getName(self) -> str:
        return self.contextSym.getName()

    def setNameIfUnset(self, name: str) -> None:
        self.contextSym.setNameIfUnset(name)

    def setNameGetCallback(self, callback: Callable[[common.ContextSymbol], str]) -> None:
        self.contextSym.setNameGetCallback(callback)

    def setNameGetCallbackIfUnset(self, callback: Callable[[common.ContextSymbol], str]) -> None:
        self.contextSym.setNameGetCallbackIfUnset(callback)


    def generateAsmLineComment(self, localOffset: int, wordValue: int|None = None) -> str:
        if not common.GlobalConfig.ASM_COMMENT:
            return ""

        offsetHex = "{0:0{1}X}".format(localOffset + self.inFileOffset + self.commentOffset, common.GlobalConfig.ASM_COMMENT_OFFSET_WIDTH)

        currentVram = self.getVramOffset(localOffset)
        vramHex = f"{currentVram:08X}"

        wordValueHex = ""
        if wordValue is not None:
            wordValueHex = f"{common.Utils.beWordToCurrenEndian(wordValue):08X} "

        return f"/* {offsetHex} {vramHex} {wordValueHex}*/"

    def getSymbolAtVramOrOffset(self, localOffset: int) -> common.ContextSymbol|None:
        contextSym = self.context.getOffsetSymbol(self.inFileOffset + localOffset, self.sectionType)
        if contextSym is not None:
            return contextSym

        currentVram = self.getVramOffset(localOffset)
        return self.getSymbol(currentVram, tryPlusOffset=False)

    def getLabel(self) -> str:
        if self.contextSym is not None:
            return self.getLabelFromSymbol(self.contextSym)

        offsetSym = self.context.getOffsetSymbol(self.inFileOffset, self.sectionType)
        return self.getLabelFromSymbol(offsetSym)


    def isRdata(self) -> bool:
        "Checks if the current symbol is .rdata"
        return False


    def renameBasedOnType(self):
        pass


    def analyze(self):
        self.renameBasedOnType()

        byteStep = 4
        if self.contextSym.isByte():
            byteStep = 1
        elif self.contextSym.isShort():
            byteStep = 2

        if self.sectionType != common.FileSectionType.Bss:
            for i in range(0, self.sizew):
                localOffset = 4*i
                for j in range(0, 4, byteStep):
                    if i == 0 and j == 0:
                        continue
                    contextSym = self.getSymbolAtVramOrOffset(localOffset+j)
                    if contextSym is not None:
                        contextSym.vromAddress = self.getVromOffset(localOffset+j)
                        contextSym.isDefined = True
                        contextSym.sectionType = self.sectionType
                        if contextSym.hasNoType():
                            contextSym.type = contextSym.type


    def getNthWord(self, i: int, canReferenceSymbolsWithAddends: bool=False, canReferenceConstants: bool=False) -> tuple[str, int]:
        output = ""
        localOffset = 4*i
        w = self.words[i]

        isByte = False
        isShort = False
        if self.contextSym.isByte():
            isByte = True
        elif self.contextSym.isShort():
            isShort = True

        dotType = ".word"
        byteStep = 4
        if isByte:
            dotType = ".byte"
            byteStep = 1
        elif isShort:
            dotType = ".short"
            byteStep = 2

        for j in range(0, 4, byteStep):
            label = ""
            if j != 0 or i != 0:
                contextSym = self.getSymbolAtVramOrOffset(localOffset+j)
                if contextSym is not None:
                    # Possible symbols in the middle
                    label = common.GlobalConfig.LINE_ENDS + contextSym.getSymbolLabel()  + common.GlobalConfig.LINE_ENDS

            if isByte:
                shiftValue = 24 - (j * 8)
                subVal = (w & (0xFF << shiftValue)) >> shiftValue
                value = f"0x{subVal:02X}"
            elif isShort:
                shiftValue = 16 - (j * 8)
                subVal = (w & (0xFFFF << shiftValue)) >> shiftValue
                value = f"0x{subVal:04X}"
            else:
                value = f"0x{w:08X}"

                # .elf relocated symbol
                if len(self.context.relocSymbols[self.sectionType]) > 0:
                    possibleReference = self.context.getRelocSymbol(self.inFileOffset + localOffset, self.sectionType)
                    if possibleReference is not None:
                        value = possibleReference.getNamePlusOffset(w)
                else:
                    # This word could be a reference to a symbol
                    symbolRef = self.getSymbol(w, tryPlusOffset=canReferenceSymbolsWithAddends)
                    if symbolRef is not None:
                        value = symbolRef.getSymbolPlusOffset(w)
                    elif canReferenceConstants:
                        constant = self.getConstant(w)
                        if constant is not None:
                            value = constant.getName()

            comment = self.generateAsmLineComment(localOffset+j)
            output += f"{label}{comment} {dotType} {value}"
            if j == 0 and i < len(self.endOfLineComment):
                output += self.endOfLineComment[i]
            output += common.GlobalConfig.LINE_ENDS

        return output, 0


    def disassembleAsData(self) -> str:
        output = self.getLabel()

        canReferenceSymbolsWithAddends = self.canUseAddendsOnData()
        canReferenceConstants = self.canUseConstantsOnData()

        i = 0
        while i < self.sizew:
            data, skip = self.getNthWord(i, canReferenceSymbolsWithAddends, canReferenceConstants)
            output += data

            i += skip
            i += 1
        return output

    def disassemble(self) -> str:
        return self.disassembleAsData()
