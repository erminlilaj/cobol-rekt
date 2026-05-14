       IDENTIFICATION DIVISION.
       PROGRAM-ID. RUNTIMEK.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4).
       01 WS-B PIC 9(4).
       01 WS-C PIC 9(4).
       01 WS-D PIC 9(4).
       01 WS-REF PIC 9(4).
       01 WS-CONTENT PIC 9(4).
       01 WS-VALUE PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 10 TO WS-A
           ACCEPT WS-A FROM DATE
           MOVE WS-A TO WS-C
           MOVE 20 TO WS-B
           INITIALIZE WS-B
           MOVE 30 TO WS-REF
           MOVE 40 TO WS-CONTENT
           MOVE 50 TO WS-VALUE
           CALL "SUBPROG" USING WS-REF
                                BY CONTENT WS-CONTENT
                                BY VALUE WS-VALUE
           MOVE 60 TO WS-D
           GOBACK.
