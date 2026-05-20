       IDENTIFICATION DIVISION.
       PROGRAM-ID. PERFKILL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(2).
       01 WS-B PIC 9(2).
       01 WS-C PIC 9(2).
       01 WS-D PIC 9(2).
       01 WS-E PIC 9(2).
       01 WS-F PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 10 TO WS-A
           PERFORM SUB-PARA
           MOVE WS-A TO WS-B
           MOVE 20 TO WS-C
           PERFORM CLEAN-PARA
           MOVE WS-C TO WS-D
           MOVE 30 TO WS-E
           PERFORM SUB-A
           MOVE WS-E TO WS-F
           GOBACK.
       SUB-PARA.
           MOVE 99 TO WS-A.
       CLEAN-PARA.
           DISPLAY "NO WRITE".
       SUB-A.
           PERFORM SUB-B.
       SUB-B.
           MOVE 77 TO WS-E.
