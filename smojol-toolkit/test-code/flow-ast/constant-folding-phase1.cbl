       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONSTFOLD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4).
       01 WS-B PIC 9(4).
       01 WS-C PIC 9(4).
       01 WS-D PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE WS-A = 1 + 2
           COMPUTE WS-B = WS-A + 1
           COMPUTE WS-C = 1 / 0
           MOVE 7 TO WS-D
           GOBACK.
