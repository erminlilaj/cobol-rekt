       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONSTFOLD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4).
       01 WS-B PIC 9(4).
       01 WS-C PIC 9(4).
       01 WS-D PIC 9(4).
       01 WS-E PIC S9(4).
       01 WS-F PIC 9(4)V99.
       01 WS-G PIC 9(4)V99.
       01 WS-H PIC 9(4)V99.
       01 WS-I PIC 9(4).
       01 WS-J PIC 9(4).
       01 WS-K PIC 9(4).
       01 WS-L PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE WS-A = 1 + 2
           COMPUTE WS-B = WS-A + 1
           COMPUTE WS-C = 1 / 0
           MOVE 7 TO WS-D
           COMPUTE WS-E = (1 + 2) * -3
           COMPUTE WS-F = 1.20 + 2.30
           COMPUTE WS-G = 1 / 4
           COMPUTE WS-H = 1 / 3
           COMPUTE WS-I = ZERO + 1
           COMPUTE WS-J = 2 ** 3
           COMPUTE WS-K = 10 - 3
           COMPUTE WS-L = +4
           GOBACK.
