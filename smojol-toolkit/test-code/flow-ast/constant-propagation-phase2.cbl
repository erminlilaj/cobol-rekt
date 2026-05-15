       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROP2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4).
       01 WS-B PIC 9(4).
       01 WS-C PIC 9(4).
       01 WS-D PIC 9(4).
       01 WS-E PIC 9(4).
       01 SOME-GROUP.
          05 CHILD-A PIC 9(4).
          05 CHILD-B PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 10 TO WS-A
           COMPUTE WS-B = 1 + 2
           MOVE WS-A TO WS-C
           IF WS-A = 10
               MOVE 20 TO WS-D
           ELSE
               MOVE 30 TO WS-D
           END-IF
           MOVE 99 TO CHILD-A
           COMPUTE WS-E = WS-A + 5
           GOBACK.
