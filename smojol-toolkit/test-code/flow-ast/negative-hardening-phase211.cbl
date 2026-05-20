       IDENTIFICATION DIVISION.
       PROGRAM-ID. NEGHARD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "INFILE".
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC          PIC X(2).
       WORKING-STORAGE SECTION.
       01 WS-REC-COPY      PIC X(2).
       01 WS-TEXT          PIC X(4).
       01 WS-TALLY         PIC 9(2).
       01 WS-TALLY-COPY    PIC 9(2).
       01 WS-FLAG          PIC X(1).
          88 FLAG-ON       VALUE "Y".
       01 WS-FLAG-COPY     PIC X(1).
       01 WS-MULTI-A       PIC 9(2).
       01 WS-MULTI-B       PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "AA" TO IN-REC
           READ IN-FILE
               AT END CONTINUE
           END-READ
           MOVE IN-REC TO WS-REC-COPY
           MOVE 3 TO WS-TALLY
           INSPECT WS-TEXT TALLYING WS-TALLY FOR ALL "A"
           MOVE WS-TALLY TO WS-TALLY-COPY
           MOVE "N" TO WS-FLAG
           SET FLAG-ON TO TRUE
           MOVE WS-FLAG TO WS-FLAG-COPY
           MOVE 7 TO WS-MULTI-A WS-MULTI-B
           GOBACK.
