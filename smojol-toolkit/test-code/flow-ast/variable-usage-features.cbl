       IDENTIFICATION DIVISION.
       PROGRAM-ID. VARIABLE-USAGE-FEATURES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  IN-1             PIC 9(4).
       01  IN-2             PIC 9(4).
       01  OUT-1            PIC 9(4).
       01  OUT-2            PIC 9(4).
       01  COUNTER          PIC 9(4).
       01  RESULT           PIC 9(4).
       01  TOTAL            PIC 9(4).
       01  FLAG             PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE IN-1 TO OUT-1 OUT-2.
           COMPUTE RESULT = IN-2 + COUNTER.
           ADD IN-2 TO TOTAL.
           IF FLAG = 'Y'
               MOVE TOTAL TO OUT-1
           END-IF.
           DISPLAY OUT-1.
           GOBACK.
